"""
compilatore_cro.py
==================
Compilatore completo per il linguaggio C-ro.

C-ro è un sottoinsieme del linguaggio C con parole chiave ispirate al
dialetto napoletano. Il compilatore è strutturato nelle fasi classiche:

  Sorgente .cro
       │
       ▼
  Lexer + Parser  (Lark)          ← SEZIONE 1: grammatica
       │
       ▼
  AST  (albero sintattico astratto) ← SEZIONE 2: dataclass
       │
       ▼
  Analisi Semantica               ← SEZIONE 3: scoping + type-check
  (scoping + type-checking)
       │
       ▼
  Code Gen  (Visitor + riflessione) ← SEZIONE 4: genera codice C
       │
       ▼
  Sorgente C standard

Uso:
    python compilatore_cro.py sorgente.cro          # stampa C su stdout
    python compilatore_cro.py sorgente.cro -o out.c # scrive in file
    python compilatore_cro.py --self-test           # esegue i test interni

Dipendenze:
    pip install lark
"""

from __future__ import annotations

import sys
import argparse
from dataclasses import dataclass, field
from typing import Optional, List, Any

# =============================================================================
# SEZIONE 1 – GRAMMATICA LARK (Lexer + Parser)
# =============================================================================
# Convenzioni Lark usate:
#   - regole in minuscolo       → parser (producono nodi nell'albero)
#   - TERMINALI in MAIUSCOLO    → lexer  (token)
#   - alias "-> nome"           → etichetta usata nel Transformer
#   - strings anonime "if" ecc. → la keyword è scartata dall'albero (keepall=False)
#
# La grammatica usa regole ausiliarie (elif_clause, else_clause, for_init…)
# invece di raggruppamenti "(A B)*" non supportati da Lark.
# =============================================================================

GRAMMATICA_CRO = r"""
// -------------------------------------------------------------- Programma
start: declaration*

declaration: var_decl
           | function_decl

// --------------------------------------------------------- Dichiarazioni var
// Forma 1:  tipo ID = expr ;
// Forma 2:  tipo ID ;
var_decl: type ID "=" expr ";" -> var_decl_init
        | type ID ";"          -> var_decl_noinit

// ----------------------------------------------------- Dichiarazioni funzione
// funzion tipo nome ( params? ) { corpo }
// tipo capo ()                  { corpo }
function_decl: "funzion" type ID "(" params? ")" block -> function_decl
             | type "capo" "(" ")"              block -> main_decl

params: param ("," param)*
param:  type ID

// --------------------------------------------------------------- Blocco
block: "{" statement* "}"

// -------------------------------------------------------------- Statement
statement: var_decl
         | if_stmt
         | switch_stmt
         | while_stmt
         | for_stmt
         | do_while_stmt
         | return_stmt
         | break_stmt
         | continue_stmt
         | expr ";"   -> expr_stmt
         | block

// ------------------------------------------------------- Strutture di controllo
if_stmt: "if" "(" expr ")" statement elif_clause* else_clause?
elif_clause: "S'invece" "(" expr ")" statement
else_clause: "else" statement

switch_stmt:  "facimm" "(" expr ")" "{" case_stmt* default_stmt? "}"
case_stmt:    "cas" expr ":"    statement*
default_stmt: "default" ":"     statement*

while_stmt:    "trament" "(" expr ")" statement
for_stmt:      "ppe" "(" for_init expr? ";" expr? ")" statement
for_init:      var_decl
             | expr ";" -> for_init_expr
             | ";"      -> for_init_empty
do_while_stmt: "faje" statement "trament" "(" expr ")" ";"

// ------------------------------------------------------------- Jump statements
return_stmt:   "torn"  expr? ";"
break_stmt:    "spacc" ";"
continue_stmt: "vaje"  ";"

// --------------------------------------------------------------- Espressioni
// Grammatica a strati per gestire le precedenze senza ambiguità.
//   assegnazione  (destra-associativa, precedenza minima)
//   ||  &&        (logici)
//   == !=  < <= > >=  (confronto)
//   + -  * / %    (aritmetici)
//   not  -unario  (unari)
//   atomo         (precedenza massima)
//
// assign_expr NON usa il prefisso '?' per evitare conflitti con gli alias.
?expr: assign_expr

assign_expr: logical_or_expr "=" assign_expr -> assign_expr
           | logical_or_expr                 -> passthrough

logical_or_expr:  logical_and_expr ("o"   logical_and_expr)* -> or_expr
logical_and_expr: equality_expr    ("e"   equality_expr)*    -> and_expr
equality_expr:    relational_expr  (EQOP  relational_expr)*  -> eq_expr
relational_expr:  add_expr         (RELOP add_expr)*         -> rel_expr
add_expr:         mul_expr         (ADDOP mul_expr)*         -> add_expr
mul_expr:         unary_expr       (MULOP unary_expr)*       -> mul_expr

unary_expr: "non" unary_expr -> not_expr
           | "-"  unary_expr -> neg_expr
           | primary_expr

primary_expr: INT_CONST     -> int_const
            | FLOAT_CONST   -> float_const
            | STRING_CONST  -> string_const
            | CHAR_CONST    -> char_const
            | "over"        -> true_const
            | "favz"        -> false_const
            | "(" expr ")"
            | function_call
            | ID            -> var_ref

// Chiamata a funzione (include le built-in stambf e scanef)
function_call: CALLABLE "(" args? ")"
CALLABLE: "stambf" | "scanef" | ID

args: expr ("," expr)*

// -------------------------------------------------------------------- Tipi
type: "nummero"   -> t_int
    | "comm"      -> t_float
    | "carattere" -> t_char
    | "bull"      -> t_bool
    | "a vacant"  -> t_void
    | "const" type -> t_const

// ================================================================== TERMINALI
EQOP:  "==" | "!="
RELOP: "<=" | ">=" | "<" | ">"
ADDOP: "+" | "-"
MULOP: "*" | "/" | "%"

FLOAT_CONST:  /\d+\.\d+/
INT_CONST:    /\d+/
STRING_CONST: /\"([^\"\\]|\\.)*\"/
CHAR_CONST:   /\'([^\'\\]|\\.)\'/

// ID esclude le parole chiave riservate (lookahead negativo) per evitare
// ambiguità tra operatori testuali (e, o, non) / keyword e identificatori
// (es. "non (x)" come operatore unario vs chiamata a funzione "non(x)").
ID: /(?!(?:nummero|comm|carattere|bull|const|over|favz|if|else|facimm|cas|default|trament|ppe|faje|spacc|vaje|capo|funzion|torn|stambf|scanef|non|e|o)\b)[a-zA-Z_][a-zA-Z0-9_]*/

%ignore /\/\/[^\n]*/
%ignore /\/\*(.|\n)*?\*\//
%ignore /\s+/
"""

# =============================================================================
# SEZIONE 2 – NODI DELL'ALBERO SINTATTICO ASTRATTO (AST)
# =============================================================================
# Ogni nodo è una dataclass Python (solo dati, nessuna logica).
# La logica è concentrata nei Visitor delle sezioni successive.
# =============================================================================

@dataclass
class ProgramNode:
    declarations: List[Any] = field(default_factory=list)

@dataclass
class TypeNode:
    name: str           # 'int' | 'float' | 'char' | 'bool' | 'void'
    const: bool = False

@dataclass
class VarDeclNode:
    var_type: TypeNode
    name: str
    init_expr: Optional[Any] = None

@dataclass
class ParamNode:
    param_type: TypeNode
    name: str

@dataclass
class FunctionDeclNode:
    ret_type: TypeNode
    name: str
    params: List[ParamNode]
    body: 'BlockNode'
    is_main: bool = False

@dataclass
class BlockNode:
    statements: List[Any] = field(default_factory=list)

@dataclass
class IfNode:
    condition: Any
    then_branch: Any
    elif_clauses: List[tuple]   # lista di (condizione, corpo)
    else_branch: Optional[Any] = None

@dataclass
class SwitchNode:
    expr: Any
    cases: List['CaseNode']
    default: Optional['DefaultNode'] = None

@dataclass
class CaseNode:
    expr: Any
    statements: List[Any]

@dataclass
class DefaultNode:
    statements: List[Any]

@dataclass
class WhileNode:
    condition: Any
    body: Any

@dataclass
class ForNode:
    init: Any
    condition: Optional[Any]
    update: Optional[Any]
    body: Any

@dataclass
class DoWhileNode:
    body: Any
    condition: Any

@dataclass
class ReturnNode:
    expr: Optional[Any] = None

@dataclass
class BreakNode: pass
@dataclass
class ContinueNode: pass

@dataclass
class ExprStmtNode:
    expr: Any

@dataclass
class AssignNode:
    target: Any
    value: Any

@dataclass
class BinOpNode:
    op: str
    left: Any
    right: Any

@dataclass
class UnOpNode:
    op: str
    operand: Any

@dataclass
class IntConstNode:    value: int
@dataclass
class FloatConstNode:  value: float
@dataclass
class StringConstNode: value: str
@dataclass
class CharConstNode:   value: str
@dataclass
class BoolConstNode:   value: bool

@dataclass
class VarRefNode:
    name: str

@dataclass
class FunctionCallNode:
    name: str
    args: List[Any]

# =============================================================================
# SEZIONE 3 – TRANSFORMER LARK → AST
# =============================================================================

from lark import Lark, Transformer, Token, Tree

class CroTransformer(Transformer):

    # ---- Programma ---------------------------------------------------------
    def start(self, items):
        return ProgramNode(declarations=list(items))

    def declaration(self, items):
        return items[0]

    # ---- Tipi --------------------------------------------------------------
    def t_int(self, _):        return TypeNode('int')
    def t_float(self, _):      return TypeNode('float')
    def t_char(self, _):       return TypeNode('char')
    def t_bool(self, _):       return TypeNode('bool')
    def t_void(self, _):       return TypeNode('void')
    def t_const(self, items):  return TypeNode(items[0].name, const=True)

    # ---- Dichiarazioni variabile -------------------------------------------
    def var_decl_init(self, items):
        return VarDeclNode(var_type=items[0], name=str(items[1]), init_expr=items[2])

    def var_decl_noinit(self, items):
        return VarDeclNode(var_type=items[0], name=str(items[1]))

    # ---- Dichiarazioni funzione --------------------------------------------
    def params(self, items): return list(items)
    def param(self, items):  return ParamNode(param_type=items[0], name=str(items[1]))

    def function_decl(self, items):
        ret_type = items[0]
        name = str(items[1])
        if isinstance(items[2], list):           # ci sono parametri
            params, body = items[2], items[3]
        else:
            params, body = [], items[2]
        return FunctionDeclNode(ret_type=ret_type, name=name, params=params, body=body)

    def main_decl(self, items):
        return FunctionDeclNode(ret_type=items[0], name='main',
                                params=[], body=items[1], is_main=True)

    # ---- Blocco e statement ------------------------------------------------
    def block(self, items):
        return BlockNode(statements=list(items))

    def statement(self, items):
        return items[0]

    def expr_stmt(self, items):
        return ExprStmtNode(expr=items[0])

    # ---- if / elif / else --------------------------------------------------
    def if_stmt(self, items):
        cond     = items[0]
        then     = items[1]
        elifs    = [i for i in items[2:] if isinstance(i, tuple)]
        else_br  = next((i for i in items[2:] if not isinstance(i, tuple)), None)
        return IfNode(condition=cond, then_branch=then,
                      elif_clauses=elifs, else_branch=else_br)

    def elif_clause(self, items):
        return (items[0], items[1])     # (condizione, corpo) come tuple

    def else_clause(self, items):
        return items[0]

    # ---- switch ------------------------------------------------------------
    def switch_stmt(self, items):
        expr = items[0]
        cases   = [i for i in items[1:] if isinstance(i, CaseNode)]
        default = next((i for i in items[1:] if isinstance(i, DefaultNode)), None)
        return SwitchNode(expr=expr, cases=cases, default=default)

    def case_stmt(self, items):
        return CaseNode(expr=items[0], statements=list(items[1:]))

    def default_stmt(self, items):
        return DefaultNode(statements=list(items))

    # ---- cicli -------------------------------------------------------------
    def while_stmt(self, items):
        return WhileNode(condition=items[0], body=items[1])

    def for_stmt(self, items):
        # items: [for_init, (cond | None), (upd | None)?, body]
        init = items[0]
        # Gli expr opzionali nel for sono Token vuoti se assenti → li filtriamo
        rest = [i for i in items[1:] if not isinstance(i, Token)]
        # rest può avere 1 (body), 2 (cond+body o upd+body) o 3 elementi
        if len(rest) == 1:
            cond, upd, body = None, None, rest[0]
        elif len(rest) == 2:
            cond, upd, body = rest[0], None, rest[1]
        else:
            cond, upd, body = rest[0], rest[1], rest[2]
        return ForNode(init=init, condition=cond, update=upd, body=body)

    def for_init_expr(self, items):  return ExprStmtNode(expr=items[0])
    def for_init_empty(self, _):     return None

    def do_while_stmt(self, items):
        return DoWhileNode(body=items[0], condition=items[1])

    # ---- jump --------------------------------------------------------------
    def return_stmt(self, items):
        return ReturnNode(expr=items[0] if items else None)

    def break_stmt(self, _):    return BreakNode()
    def continue_stmt(self, _): return ContinueNode()

    # ---- Espressioni -------------------------------------------------------
    def assign_expr(self, items):
        return AssignNode(target=items[0], value=items[1])

    def passthrough(self, items):
        return items[0]

    def or_expr(self, items):
        return self._left_fold(items, '||')

    def and_expr(self, items):
        return self._left_fold(items, '&&')

    def eq_expr(self, items):
        return self._interleaved(items)

    def rel_expr(self, items):
        return self._interleaved(items)

    def add_expr(self, items):
        return self._interleaved(items)

    def mul_expr(self, items):
        return self._interleaved(items)

    def _left_fold(self, items, op):
        """Costruisce albero sx-associativo da una lista di SOLI operandi
        [E, E, E, ...]; gli operatori 'e'/'o' sono parole chiave e Lark li
        filtra dall'albero (token anonimi), quindi non compaiono in `items`."""
        result = items[0]
        for right in items[1:]:
            result = BinOpNode(op, result, right)
        return result

    def _interleaved(self, items):
        """Lista [E, Token(op), E, Token(op), E, ...]"""
        result = items[0]
        i = 1
        while i < len(items):
            op    = str(items[i])
            right = items[i + 1]
            result = BinOpNode(op, result, right)
            i += 2
        return result

    # primary_expr alternative "(" expr ")" e function_call non hanno alias →
    # Lark crea Tree("primary_expr", [child]); appiattisci
    def primary_expr(self, items): return items[0]

    # unary_expr terza alternativa (| primary_expr) non ha alias →
    # Lark crea Tree("unary_expr", [primary_result]); questo metodo la appiattisce
    def unary_expr(self, items): return items[0]

    # for_init terza alternativa (var_decl) non ha alias → appiattisci
    def for_init(self, items): return items[0]

    def not_expr(self, items): return UnOpNode('!', items[0])
    def neg_expr(self, items): return UnOpNode('-', items[0])

    def int_const(self, items):    return IntConstNode(int(str(items[0])))
    def float_const(self, items):  return FloatConstNode(float(str(items[0])))
    def string_const(self, items): return StringConstNode(str(items[0]))
    def char_const(self, items):   return CharConstNode(str(items[0]))
    def true_const(self, _):       return BoolConstNode(True)
    def false_const(self, _):      return BoolConstNode(False)
    def var_ref(self, items):      return VarRefNode(str(items[0]))

    def function_call(self, items):
        name = str(items[0])
        args = items[1] if len(items) > 1 else []
        return FunctionCallNode(name=name, args=args)

    def args(self, items): return list(items)

# =============================================================================
# SEZIONE 4 – ANALISI SEMANTICA
# =============================================================================

class SemanticError(Exception):
    pass

class SymbolTable:
    def __init__(self, parent: Optional['SymbolTable'] = None, scope_name: str = "global"):
        self.symbols: dict = {}
        self.parent  = parent
        self.scope_name = scope_name

    def define(self, name: str, info: dict):
        if name in self.symbols:
            raise SemanticError(
                f"'{name}' già dichiarato nello scope '{self.scope_name}'.")
        self.symbols[name] = info

    def lookup(self, name: str) -> Optional[dict]:
        if name in self.symbols:
            return self.symbols[name]
        return self.parent.lookup(name) if self.parent else None

class SemanticAnalyzer:

    def __init__(self):
        self.global_table   = SymbolTable(scope_name="global")
        self.current_table  = self.global_table
        self.current_fun: Optional[FunctionDeclNode] = None
        self.errors: List[str] = []

    def analyze(self, node: ProgramNode) -> bool:
        self._visit(node)
        return len(self.errors) == 0

    # ---- Infrastruttura Visitor --------------------------------------------

    def _visit(self, node) -> Optional[str]:
        method = getattr(self, f'_v_{node.__class__.__name__}', None)
        if method:
            return method(node)
        return None

    def _compatible(self, t1: str, t2: str) -> bool:
        numeric = {'int', 'float'}
        if t1 == t2:          return True
        if t1 in numeric and t2 in numeric: return True
        return False

    def _result_type(self, t1: str, t2: str) -> str:
        return 'float' if 'float' in (t1, t2) else t1

    def _err(self, msg: str):
        self.errors.append(msg)

    # ---- Nodi --------------------------------------------------------------

    def _v_ProgramNode(self, node: ProgramNode):
        for d in node.declarations:
            self._visit(d)

    def _v_VarDeclNode(self, node: VarDeclNode):
        if node.init_expr is not None:
            init_t = self._visit(node.init_expr)
            base   = node.var_type.name
            if init_t and not self._compatible(base, init_t):
                self._err(f"Type mismatch: '{node.name}' è '{base}' "
                          f"ma l'inizializzatore è '{init_t}'.")
        try:
            self.current_table.define(node.name, {
                'kind':  'var',
                'type':  node.var_type.name,
                'const': node.var_type.const,
            })
        except SemanticError as e:
            self._err(str(e))
        return node.var_type.name

    def _v_FunctionDeclNode(self, node: FunctionDeclNode):
        param_types = [p.param_type.name for p in node.params]
        try:
            self.global_table.define(node.name, {
                'kind':        'function',
                'ret_type':    node.ret_type.name,
                'param_types': param_types,
            })
        except SemanticError as e:
            self._err(str(e))

        prev_table = self.current_table
        prev_fun   = self.current_fun
        self.current_table = SymbolTable(parent=prev_table,
                                         scope_name=f"fun:{node.name}")
        self.current_fun = node

        for p in node.params:
            try:
                self.current_table.define(p.name, {'kind':'param','type':p.param_type.name})
            except SemanticError as e:
                self._err(str(e))

        self._v_BlockNode(node.body, new_scope=False)   # scope già aperto

        self.current_table = prev_table
        self.current_fun   = prev_fun

    def _v_BlockNode(self, node: BlockNode, new_scope: bool = True):
        if new_scope:
            prev = self.current_table
            self.current_table = SymbolTable(parent=prev, scope_name="block")

        for s in node.statements:
            self._visit(s)

        if new_scope:
            self.current_table = prev

    def _v_ExprStmtNode(self, n): self._visit(n.expr)

    def _v_IfNode(self, node: IfNode):
        ct = self._visit(node.condition)
        if ct and ct != 'bool':
            self._err(f"Condizione 'if' non booleana (trovato '{ct}').")
        self._visit(node.then_branch)
        for cond, body in node.elif_clauses:
            ct2 = self._visit(cond)
            if ct2 and ct2 != 'bool':
                self._err(f"Condizione 'S'invece' non booleana (trovato '{ct2}').")
            self._visit(body)
        if node.else_branch:
            self._visit(node.else_branch)

    def _v_WhileNode(self, node: WhileNode):
        ct = self._visit(node.condition)
        if ct and ct != 'bool':
            self._err(f"Condizione 'trament' non booleana (trovato '{ct}').")
        self._visit(node.body)

    def _v_ForNode(self, node: ForNode):
        if node.init:      self._visit(node.init)
        if node.condition: self._visit(node.condition)
        if node.update:    self._visit(node.update)
        self._visit(node.body)

    def _v_DoWhileNode(self, node: DoWhileNode):
        self._visit(node.body)
        ct = self._visit(node.condition)
        if ct and ct != 'bool':
            self._err(f"Condizione 'faje...trament' non booleana (trovato '{ct}').")

    def _v_SwitchNode(self, node: SwitchNode):
        self._visit(node.expr)
        for c in node.cases:   self._visit(c)
        if node.default:       self._visit(node.default)

    def _v_CaseNode(self, node: CaseNode):
        self._visit(node.expr)
        for s in node.statements: self._visit(s)

    def _v_DefaultNode(self, node: DefaultNode):
        for s in node.statements: self._visit(s)

    def _v_ReturnNode(self, node: ReturnNode):
        if self.current_fun is None:
            self._err("'torn' fuori da una funzione."); return
        expected = self.current_fun.ret_type.name
        if node.expr is None:
            if expected != 'void':
                self._err(f"'{self.current_fun.name}' deve restituire '{expected}'.")
        else:
            rt = self._visit(node.expr)
            if rt and not self._compatible(expected, rt):
                self._err(f"Tipo ritorno '{self.current_fun.name}': "
                          f"atteso '{expected}', trovato '{rt}'.")

    def _v_BreakNode(self, _):    pass
    def _v_ContinueNode(self, _): pass

    # ---- Espressioni -------------------------------------------------------

    def _v_IntConstNode(self, _):    return 'int'
    def _v_FloatConstNode(self, _):  return 'float'
    def _v_StringConstNode(self, _): return 'char*'
    def _v_CharConstNode(self, _):   return 'char'
    def _v_BoolConstNode(self, _):   return 'bool'

    def _v_VarRefNode(self, node: VarRefNode):
        entry = self.current_table.lookup(node.name)
        if entry is None:
            self._err(f"Identificatore non dichiarato: '{node.name}'."); return None
        return entry.get('type')

    def _v_AssignNode(self, node: AssignNode):
        if not isinstance(node.target, VarRefNode):
            self._err("Sinistra dell'assegnazione deve essere una variabile."); return None
        entry = self.current_table.lookup(node.target.name)
        if entry is None:
            self._err(f"Identificatore non dichiarato: '{node.target.name}'."); return None
        if entry.get('const'):
            self._err(f"Assegnazione a costante: '{node.target.name}'.")
        lt = entry.get('type')
        rt = self._visit(node.value)
        if rt and not self._compatible(lt, rt):
            self._err(f"Type mismatch: '{node.target.name}' è '{lt}', valore '{rt}'.")
        return lt

    def _v_BinOpNode(self, node: BinOpNode):
        lt = self._visit(node.left)
        rt = self._visit(node.right)
        op = node.op
        if op in ('&&', '||'):
            for t, side in [(lt,'sx'), (rt,'dx')]:
                if t and t != 'bool':
                    self._err(f"Operatore '{op}' lato {side}: booleano atteso, trovato '{t}'.")
            return 'bool'
        if op in ('==','!=','<','<=','>','>='):
            if lt and rt and not self._compatible(lt, rt):
                self._err(f"Confronto '{op}': tipi incompatibili '{lt}' e '{rt}'.")
            return 'bool'
        if op in ('+','-','*','/','%'):
            if lt and rt and not self._compatible(lt, rt):
                self._err(f"Aritmetica '{op}': tipi incompatibili '{lt}' e '{rt}'."); return None
            if lt and rt: return self._result_type(lt, rt)
        return None

    def _v_UnOpNode(self, node: UnOpNode):
        t = self._visit(node.operand)
        if node.op == '!':
            if t and t != 'bool':
                self._err(f"'non' richiede booleano, trovato '{t}'.")
            return 'bool'
        if node.op == '-':
            if t and t not in ('int','float'):
                self._err(f"Negazione unaria richiede numerico, trovato '{t}'.")
            return t
        return t

    def _v_FunctionCallNode(self, node: FunctionCallNode):
        if node.name in ('stambf','printf','scanef','scanf'):
            for a in node.args: self._visit(a)
            return 'void'
        entry = self.global_table.lookup(node.name)
        if entry is None or entry.get('kind') != 'function':
            self._err(f"Funzione non dichiarata: '{node.name}'."); return None
        ep = entry.get('param_types', [])
        if len(ep) != len(node.args):
            self._err(f"'{node.name}': attesi {len(ep)} arg, dati {len(node.args)}.")
        else:
            for i, (et, aa) in enumerate(zip(ep, node.args)):
                at = self._visit(aa)
                if at and not self._compatible(et, at):
                    self._err(f"Arg {i+1} di '{node.name}': atteso '{et}', trovato '{at}'.")
        return entry.get('ret_type')

    def _v_ExprStmt(self, n): self._visit(n.expr)

# =============================================================================
# SEZIONE 5 – GENERATORE DI CODICE C  (Visitor con riflessione)
# =============================================================================

class CodeGenerator:
    """Traduce l'AST validato in codice C standard.

    Schema di indentazione: ogni metodo che genera codice multi-riga
    restituisce una stringa la cui PRIMA riga è a colonna 0; il contenuto
    interno è indentato di UN livello relativo (4 spazi) tramite
    `_indent_lines`. Quando questa stringa viene inserita in un contesto
    già indentato, l'intero blocco (incluse le righe interne) viene
    spostato uniformemente di un livello in più dal chiamante — così
    l'annidamento si accumula correttamente senza raddoppi.
    """

    TYPE_MAP = {'int':'int','float':'float','char':'char','bool':'bool','void':'void'}

    def generate(self, node: ProgramNode) -> str:
        return self._v(node)

    def _v(self, node) -> str:
        method = getattr(self, f'_v_{node.__class__.__name__}', self._generic)
        return method(node)

    def _generic(self, node) -> str:
        raise NotImplementedError(f"CodeGen: nessun metodo per {node.__class__.__name__}")

    @staticmethod
    def _indent_lines(text: str, levels: int = 1) -> str:
        prefix = '    ' * levels
        return '\n'.join((prefix + l) if l.strip() else l for l in text.splitlines())

    def _type(self, t: TypeNode) -> str:
        return ('const ' if t.const else '') + self.TYPE_MAP.get(t.name, t.name)

    # ---- Programma ---------------------------------------------------------
    def _v_ProgramNode(self, node: ProgramNode) -> str:
        header = "#include <stdio.h>\n#include <stdbool.h>\n\n"
        return header + '\n'.join(self._v(d) for d in node.declarations)

    # ---- Dichiarazioni -----------------------------------------------------
    def _v_VarDeclNode(self, node: VarDeclNode) -> str:
        ct = self._type(node.var_type)
        if node.init_expr is not None:
            return f"{ct} {node.name} = {self._v(node.init_expr)};"
        return f"{ct} {node.name};"

    def _v_FunctionDeclNode(self, node: FunctionDeclNode) -> str:
        ret    = 'int' if node.is_main else self._type(node.ret_type)
        name   = 'main' if node.is_main else node.name
        params = ', '.join(f"{self._type(p.param_type)} {p.name}" for p in node.params)
        body   = self._v_BlockNode(node.body)
        if node.is_main:
            return f"int main(void) {body}\n"
        return f"{ret} {name}({params}) {body}\n"

    # ---- Blocco e statement -------------------------------------------------
    def _v_BlockNode(self, node: BlockNode) -> str:
        stmts = '\n'.join(self._indent_lines(self._v(s)) for s in node.statements)
        inner = ('\n' + stmts + '\n') if stmts else '\n'
        return '{' + inner + '}'

    def _v_ExprStmtNode(self, node: ExprStmtNode) -> str:
        return self._v(node.expr) + ';'

    def _v_IfNode(self, node: IfNode) -> str:
        code = f"if ({self._v(node.condition)}) {self._v_BlockNode(node.then_branch)}"
        for cond, body in node.elif_clauses:
            code += f" else if ({self._v(cond)}) {self._v_BlockNode(body)}"
        if node.else_branch:
            eb = node.else_branch
            code += f" else {self._v_BlockNode(eb) if isinstance(eb, BlockNode) else self._v(eb)}"
        return code

    def _v_SwitchNode(self, node: SwitchNode) -> str:
        cases   = '\n'.join(self._indent_lines(self._v(c)) for c in node.cases)
        default = ('\n' + self._indent_lines(self._v(node.default))) if node.default else ''
        return f"switch ({self._v(node.expr)}) {{\n{cases}{default}\n}}"

    def _v_CaseNode(self, node: CaseNode) -> str:
        stmts = '\n'.join(self._indent_lines(self._v(s)) for s in node.statements)
        return f"case {self._v(node.expr)}:\n{stmts}"

    def _v_DefaultNode(self, node: DefaultNode) -> str:
        stmts = '\n'.join(self._indent_lines(self._v(s)) for s in node.statements)
        return f"default:\n{stmts}"

    def _v_WhileNode(self, node: WhileNode) -> str:
        return f"while ({self._v(node.condition)}) {self._v_BlockNode(node.body)}"

    def _v_ForNode(self, node: ForNode) -> str:
        init = self._v(node.init).rstrip(';').strip() if node.init else ''
        cond = self._v(node.condition) if node.condition else ''
        upd  = self._v(node.update)    if node.update    else ''
        body = self._v_BlockNode(node.body)
        return f"for ({init}; {cond}; {upd}) {body}"

    def _v_DoWhileNode(self, node: DoWhileNode) -> str:
        return f"do {self._v_BlockNode(node.body)} while ({self._v(node.condition)});"

    def _v_ReturnNode(self, node: ReturnNode) -> str:
        return f"return {self._v(node.expr)};" if node.expr else "return;"

    def _v_BreakNode(self, _):    return "break;"
    def _v_ContinueNode(self, _): return "continue;"

    # ---- Espressioni ---------------------------------------------------------
    def _v_IntConstNode(self, n):    return str(n.value)
    def _v_FloatConstNode(self, n):  return str(n.value)
    def _v_StringConstNode(self, n): return n.value
    def _v_CharConstNode(self, n):   return n.value
    def _v_BoolConstNode(self, n):   return 'true' if n.value else 'false'
    def _v_VarRefNode(self, n):      return n.name

    def _v_AssignNode(self, node: AssignNode) -> str:
        return f"{self._v(node.target)} = {self._v(node.value)}"

    def _v_BinOpNode(self, node: BinOpNode) -> str:
        return f"({self._v(node.left)} {node.op} {self._v(node.right)})"

    def _v_UnOpNode(self, node: UnOpNode) -> str:
        return f"({node.op}{self._v(node.operand)})"

    def _v_FunctionCallNode(self, node: FunctionCallNode) -> str:
        name_map = {'stambf': 'printf', 'scanef': 'scanf'}
        name = name_map.get(node.name, node.name)
        args = ', '.join(self._v(a) for a in node.args)
        return f"{name}({args})"

# =============================================================================
# SEZIONE 6 – PIPELINE COMPLETA
# =============================================================================

def build_parser() -> Lark:
    return Lark(GRAMMATICA_CRO, parser='earley', ambiguity='resolve')

def compile_cro(source: str, parser: Optional[Lark] = None) -> str:
    """
    Compila il sorgente C-ro e restituisce codice C.
    Solleva ValueError per errori semantici.
    Solleva lark.exceptions.* per errori sintattici/lessicali.
    """
    if parser is None:
        parser = build_parser()

    # Fase 1: Lexing + Parsing → albero concreto Lark
    tree = parser.parse(source)

    # Fase 2: Transformer → AST
    ast = CroTransformer().transform(tree)

    # Fase 3: Analisi semantica
    analyzer = SemanticAnalyzer()
    if not analyzer.analyze(ast):
        msg = '\n'.join(f"  • {e}" for e in analyzer.errors)
        raise ValueError(f"Errori semantici:\n{msg}")

    # Fase 4: Generazione codice C
    return CodeGenerator().generate(ast)

# =============================================================================
# SEZIONE 7 – SELF-TEST
# =============================================================================

TESTS = {
    "hello world": (True, r"""
        nummero capo() {
            stambf("Hello, World!\n");
            torn 0;
        }
    """),

    "variabili e aritmetica": (True, r"""
        nummero capo() {
            nummero a = 10;
            nummero b = 3;
            nummero c = a + b;
            stambf("%d\n", c);
            torn 0;
        }
    """),

    "funzione + chiamata": (True, r"""
        funzion nummero doppio(nummero x) {
            torn x + x;
        }
        nummero capo() {
            nummero r = doppio(5);
            stambf("%d\n", r);
            torn 0;
        }
    """),

    "if-else": (True, r"""
        nummero capo() {
            nummero x = 42;
            if (x > 0) {
                stambf("pos\n");
            } else {
                stambf("neg\n");
            }
            torn 0;
        }
    """),

    "ciclo while": (True, r"""
        nummero capo() {
            nummero i = 0;
            trament (i < 5) {
                i = i + 1;
            }
            stambf("%d\n", i);
            torn 0;
        }
    """),

    "ciclo for": (True, r"""
        nummero capo() {
            nummero s = 0;
            ppe (nummero i = 0; i < 10; i = i + 1) {
                s = s + i;
            }
            stambf("%d\n", s);
            torn 0;
        }
    """),

    "do-while": (True, r"""
        nummero capo() {
            nummero n = 1;
            faje {
                n = n + 1;
            } trament (n < 5);
            stambf("%d\n", n);
            torn 0;
        }
    """),

    "tipo float": (True, r"""
        nummero capo() {
            comm x = 3.14;
            comm y = x + 1.0;
            stambf("%f\n", y);
            torn 0;
        }
    """),

    "tipo bool": (True, r"""
        nummero capo() {
            bull ok = over;
            if (ok) {
                stambf("si\n");
            }
            torn 0;
        }
    """),

    "errore semantico (var non dichiarata)": (False, r"""
        nummero capo() {
            stambf("%d\n", z);
            torn 0;
        }
    """),
}

def run_self_tests() -> bool:
    print("=" * 65)
    print("  Self-test compilatore C-ro")
    print("=" * 65)
    parser = build_parser()
    passed = 0
    for name, (should_ok, src) in TESTS.items():
        try:
            c_code = compile_cro(src, parser)
            if should_ok:
                print(f"  [OK]   {name}")
                passed += 1
            else:
                print(f"  [FAIL] {name}  (atteso errore, compilato OK)")
        except Exception as e:
            if not should_ok:
                print(f"  [OK]   {name}  (errore atteso: {e})")
                passed += 1
            else:
                print(f"  [FAIL] {name}\n         {e}")

    print(f"\nRisultato: {passed}/{len(TESTS)} test superati.\n")

    # Mostra un esempio di codice C generato
    _, src = list(TESTS.values())[2]   # "funzione + chiamata"
    try:
        print("--- Esempio di codice C generato (funzione + chiamata) ---")
        print(compile_cro(src, parser))
        print("----------------------------------------------------------")
    except Exception:
        pass

    return passed == len(TESTS)

# =============================================================================
# SEZIONE 8 – MAIN
# =============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="Compilatore C-ro → C  |  Corso EILP 2026")
    ap.add_argument('source', nargs='?', help="File sorgente .cro")
    ap.add_argument('-o', '--output', help="File di output .c (default: stdout)")
    ap.add_argument('--self-test', action='store_true',
                    help="Esegue i test interni")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if run_self_tests() else 1)

    if not args.source:
        ap.print_help(); sys.exit(1)

    try:
        with open(args.source, encoding='utf-8') as f:
            source = f.read()
    except FileNotFoundError:
        print(f"Errore: '{args.source}' non trovato.", file=sys.stderr)
        sys.exit(1)

    try:
        c_code = compile_cro(source)
    except Exception as e:
        print(f"Errore di compilazione:\n{e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(c_code)
        print(f"File C scritto in: {args.output}")
    else:
        print(c_code)

if __name__ == '__main__':
    main()