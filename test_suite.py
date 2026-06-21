"""
test_suite.py — Suite di test per il compilatore C-ro

Copre due livelli:

  1. TEST UNITARI di compilazione: per ogni costrutto del linguaggio,
     verifica che un piccolo programma C-ro venga compilato in C
     sintatticamente valido (o che un programma errato sollevi
     correttamente un errore semantico/sintattico).

  2. TEST DI INTEGRAZIONE end-to-end: prende i sorgenti .cro nella
     cartella programmi_test/, li compila in C, li compila con gcc,
     li esegue fornendo input simulato su stdin e verifica che l'output
     prodotto sia quello atteso. Include il test OBBLIGATORIO della
     calcolatrice richiesto dalla traccia d'esame (sezione 4).

Uso:
    python test_suite.py
    python test_suite.py -v        # output verboso

Richiede: pip install lark, e gcc disponibile nel PATH per i test di
integrazione (se gcc non è disponibile, quei test vengono saltati con
un avviso, non falliscono).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from compilatore_cro import compile_cro, build_parser, SemanticError
from lark.exceptions import LarkError

GCC_AVAILABLE = shutil.which("gcc") is not None


# =============================================================================
# PARTE 1 — TEST UNITARI DI COMPILAZIONE (un costrutto alla volta)
# =============================================================================

class TestCostruttiBase(unittest.TestCase):
    """Verifica che ogni costrutto sintattico/semantico del linguaggio
    venga riconosciuto e tradotto correttamente."""

    @classmethod
    def setUpClass(cls):
        cls.parser = build_parser()

    def _compila(self, src: str) -> str:
        return compile_cro(src, self.parser)

    # ---- Dichiarazioni e tipi ----------------------------------------------

    def test_dichiarazione_senza_init(self):
        c = self._compila("nummero capo() { nummero x; torn 0; }")
        self.assertIn("int x;", c)

    def test_dichiarazione_con_init(self):
        c = self._compila("nummero capo() { nummero x = 5; torn 0; }")
        self.assertIn("int x = 5;", c)

    def test_tutti_i_tipi_base(self):
        c = self._compila("""
            nummero capo() {
                nummero a = 1;
                comm b = 1.5;
                carattere c = 'x';
                bull d = over;
                torn 0;
            }
        """)
        for atteso in ("int a = 1;", "float b = 1.5;",
                       "char c = 'x';", "bool d = true;"):
            self.assertIn(atteso, c)

    def test_costante(self):
        c = self._compila("nummero capo() { const nummero X = 10; torn 0; }")
        self.assertIn("const int X = 10;", c)

    def test_errore_assegnazione_a_costante(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    const nummero X = 10;
                    X = 20;
                    torn 0;
                }
            """)

    def test_errore_identificatore_non_dichiarato(self):
        with self.assertRaises(ValueError):
            self._compila('nummero capo() { stambf("%d", y); torn 0; }')

    def test_errore_dichiarazione_multipla(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    nummero x = 1;
                    nummero x = 2;
                    torn 0;
                }
            """)

    # ---- Funzioni ------------------------------------------------------------

    def test_funzione_con_parametri_e_ritorno(self):
        c = self._compila("""
            funzion nummero somma(nummero a, nummero b) { torn a + b; }
            nummero capo() { nummero r = somma(1, 2); torn 0; }
        """)
        self.assertIn("int somma(int a, int b)", c)
        self.assertIn("somma(1, 2)", c)

    def test_chiamata_annidata(self):
        c = self._compila("""
            funzion nummero quad(nummero x) { torn x * x; }
            nummero capo() { nummero r = quad(quad(2)); torn 0; }
        """)
        self.assertIn("quad(quad(2))", c)

    def test_errore_numero_argomenti_sbagliato(self):
        with self.assertRaises(ValueError):
            self._compila("""
                funzion nummero f(nummero a, nummero b) { torn a + b; }
                nummero capo() { nummero r = f(1); torn 0; }
            """)

    def test_errore_funzione_non_dichiarata(self):
        with self.assertRaises(ValueError):
            self._compila("nummero capo() { nummero r = ghost(1); torn 0; }")

    # ---- Strutture di controllo ----------------------------------------------

    def test_if_else(self):
        c = self._compila("""
            nummero capo() {
                nummero x = 1;
                if (x > 0) { stambf("pos"); } else { stambf("neg"); }
                torn 0;
            }
        """)
        self.assertIn("if ((x > 0))", c)
        self.assertIn("} else {", c)

    def test_if_elseif_else(self):
        c = self._compila("""
            nummero capo() {
                nummero x = 2;
                if (x == 1) { stambf("uno"); }
                S'invece (x == 2) { stambf("due"); }
                else { stambf("altro"); }
                torn 0;
            }
        """)
        self.assertIn("else if ((x == 2))", c)

    def test_errore_condizione_if_non_booleana(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    nummero x = 1;
                    if (x) { stambf("a"); }
                    torn 0;
                }
            """)

    def test_while(self):
        c = self._compila("""
            nummero capo() {
                nummero i = 0;
                trament (i < 10) { i = i + 1; }
                torn 0;
            }
        """)
        self.assertIn("while ((i < 10))", c)

    def test_for(self):
        c = self._compila("""
            nummero capo() {
                nummero s = 0;
                ppe (nummero i = 0; i < 5; i = i + 1) { s = s + i; }
                torn 0;
            }
        """)
        self.assertIn("for (", c)

    def test_do_while(self):
        c = self._compila("""
            nummero capo() {
                nummero n = 0;
                faje { n = n + 1; } trament (n < 3);
                torn 0;
            }
        """)
        self.assertIn("do {", c)
        self.assertIn("} while ((n < 3));", c)

    def test_switch_case_default(self):
        c = self._compila("""
            nummero capo() {
                nummero x = 1;
                facimm (x) {
                    cas 1: stambf("uno"); spacc;
                    default: stambf("altro");
                }
                torn 0;
            }
        """)
        self.assertIn("switch (x)", c)
        self.assertIn("case 1:", c)
        self.assertIn("default:", c)
        self.assertIn("break;", c)

    # ---- Operatori -------------------------------------------------------------

    def test_operatori_aritmetici(self):
        c = self._compila("""
            nummero capo() {
                nummero r = (1 + 2) - 3 * 4 / 2;
                torn 0;
            }
        """)
        self.assertIn("+", c); self.assertIn("-", c)
        self.assertIn("*", c); self.assertIn("/", c)

    def test_operatori_relazionali(self):
        c = self._compila("""
            nummero capo() {
                bull b = (1 < 2) e (3 > 2) e (1 <= 1) e (2 >= 2)
                        e (1 == 1) e (1 != 2);
                torn 0;
            }
        """)
        for op in ("<", ">", "<=", ">=", "==", "!="):
            self.assertIn(op, c)

    def test_operatori_logici(self):
        c = self._compila("""
            nummero capo() {
                bull b = (over e favz) o non favz;
                torn 0;
            }
        """)
        self.assertIn("&&", c)
        self.assertIn("||", c)
        self.assertIn("!", c)

    def test_promozione_int_float(self):
        # nummero + comm deve essere valido (promozione) e dare risultato comm
        c = self._compila("""
            nummero capo() {
                nummero a = 2;
                comm b = 1.5;
                comm r = a + b;
                torn 0;
            }
        """)
        self.assertIn("float r", c)

    def test_errore_tipi_incompatibili(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    nummero a = 1;
                    bull b = over;
                    nummero r = a + b;
                    torn 0;
                }
            """)

    # ---- Input / Output ----------------------------------------------------

    def test_stambf_diventa_printf(self):
        c = self._compila('nummero capo() { stambf("ciao"); torn 0; }')
        self.assertIn("printf(", c)

    def test_scanef_diventa_scanf_con_indirizzo(self):
        c = self._compila("""
            nummero capo() {
                nummero x;
                scanef("%d", &x);
                torn 0;
            }
        """)
        self.assertIn("scanf(", c)
        self.assertIn("&x", c)

    def test_errore_scanef_senza_indirizzo(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    nummero x;
                    scanef("%d", x);
                    torn 0;
                }
            """)

    def test_errore_indirizzo_di_costante(self):
        with self.assertRaises(ValueError):
            self._compila("""
                nummero capo() {
                    const nummero X = 1;
                    scanef("%d", &X);
                    torn 0;
                }
            """)

    # ---- Scoping -------------------------------------------------------------

    def test_scope_separati_per_blocco(self):
        # La stessa variabile può essere ridichiarata in scope diversi
        c = self._compila("""
            nummero capo() {
                nummero i = 0;
                if (i == 0) {
                    nummero j = 1;
                    stambf("%d", j);
                }
                trament (i < 1) {
                    nummero j = 2;
                    stambf("%d", j);
                    i = i + 1;
                }
                torn 0;
            }
        """)
        self.assertIn("int j = 1;", c)
        self.assertIn("int j = 2;", c)

    def test_parametri_non_visibili_fuori_dalla_funzione(self):
        with self.assertRaises(ValueError):
            self._compila("""
                funzion nummero f(nummero a) { torn a; }
                nummero capo() { nummero r = a; torn 0; }
            """)

    # ---- Errori sintattici (gestiti da Lark) ----------------------------------

    def test_errore_sintattico_punto_e_virgola_mancante(self):
        with self.assertRaises(LarkError):
            self._compila("nummero capo() { nummero x = 5 torn 0; }")

    def test_errore_sintattico_parentesi_non_chiusa(self):
        with self.assertRaises(LarkError):
            self._compila("nummero capo( { torn 0; }")


# =============================================================================
# PARTE 2 — TEST DI INTEGRAZIONE END-TO-END (compila con gcc ed esegue)
# =============================================================================

def esegui_programma_cro(percorso_cro: Path, input_stdin: str,
                         timeout: int = 5) -> str:
    """
    Compila un sorgente .cro in C, lo compila con gcc, lo esegue fornendo
    `input_stdin` su standard input, e ritorna l'output catturato.
    """
    sorgente = percorso_cro.read_text(encoding="utf-8")
    c_code = compile_cro(sorgente)

    with tempfile.TemporaryDirectory() as tmp:
        c_path  = Path(tmp) / "programma.c"
        exe_path = Path(tmp) / ("programma.exe" if sys.platform == "win32"
                                else "programma")
        c_path.write_text(c_code, encoding="utf-8")

        compile_result = subprocess.run(
            ["gcc", "-Wall", "-Wextra", "-o", str(exe_path), str(c_path)],
            capture_output=True, text=True,
        )
        if compile_result.returncode != 0:
            raise AssertionError(
                f"gcc ha fallito la compilazione del C generato:\n"
                f"{compile_result.stderr}\n\n--- codice C ---\n{c_code}")

        run_result = subprocess.run(
            [str(exe_path)], input=input_stdin,
            capture_output=True, text=True, timeout=timeout,
        )
        return run_result.stdout


@unittest.skipUnless(GCC_AVAILABLE, "gcc non disponibile nel PATH")
class TestIntegrazioneCalcolatrice(unittest.TestCase):
    """
    Test OBBLIGATORIO richiesto dalla traccia d'esame (sezione 4):
    un programma C-ro che mostri un menu di operazioni aritmetiche, legga
    input numerico dall'utente, calcoli e restituisca il risultato tramite
    funzioni, e gestisca un ciclo di continuazione/uscita.
    """

    CALCOLATRICE = Path(__file__).parent / "calcolatrice.cro"

    def test_calcolatrice_esiste(self):
        self.assertTrue(self.CALCOLATRICE.exists(),
                        "calcolatrice.cro non trovato accanto alla suite di test")

    def test_addizione_e_uscita(self):
        # scelta=1 (somma), x=5, y=3, poi continua=0 (esci)
        out = esegui_programma_cro(self.CALCOLATRICE, "1\n5\n3\n0\n")
        self.assertIn("Risultato: 8.000000", out)
        self.assertIn("Arrivederci!", out)

    def test_sottrazione(self):
        out = esegui_programma_cro(self.CALCOLATRICE, "2\n10\n4\n0\n")
        self.assertIn("Risultato: 6.000000", out)

    def test_moltiplicazione(self):
        out = esegui_programma_cro(self.CALCOLATRICE, "3\n6\n7\n0\n")
        self.assertIn("Risultato: 42.000000", out)

    def test_divisione(self):
        out = esegui_programma_cro(self.CALCOLATRICE, "4\n8\n2\n0\n")
        self.assertIn("Risultato: 4.000000", out)

    def test_divisione_per_zero(self):
        out = esegui_programma_cro(self.CALCOLATRICE, "4\n7\n0\n0\n")
        self.assertIn("Divisione per zero", out)

    def test_scelta_non_valida(self):
        out = esegui_programma_cro(self.CALCOLATRICE, "9\n0\n")
        self.assertIn("Scelta non valida", out)

    def test_ciclo_multiple_operazioni(self):
        # addizione, poi sottrazione, poi esci: dimostra il ciclo di
        # continuazione richiesto esplicitamente dalla traccia.
        out = esegui_programma_cro(
            self.CALCOLATRICE, "1\n5\n3\n1\n2\n10\n4\n0\n"
        )
        self.assertIn("Risultato: 8.000000", out)
        self.assertIn("Risultato: 6.000000", out)
        self.assertEqual(out.count("--- Menu operazioni ---"), 2)


@unittest.skipUnless(GCC_AVAILABLE, "gcc non disponibile nel PATH")
class TestIntegrazioneAltriCostrutti(unittest.TestCase):
    """Test end-to-end addizionali su singoli costrutti, per dimostrare
    che il codice C generato non solo compila ma produce l'output corretto
    a runtime (non solo correttezza sintattica)."""

    def _compila_compila_esegui(self, sorgente_cro: str, stdin: str = "") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            cro_path = Path(tmp) / "t.cro"
            cro_path.write_text(sorgente_cro, encoding="utf-8")
            return esegui_programma_cro(cro_path, stdin)

    def test_runtime_while_somma_1_a_10(self):
        out = self._compila_compila_esegui("""
            nummero capo() {
                nummero i = 1;
                nummero somma = 0;
                trament (i <= 10) {
                    somma = somma + i;
                    i = i + 1;
                }
                stambf("%d", somma);
                torn 0;
            }
        """)
        self.assertEqual(out.strip(), "55")

    def test_runtime_funzione_ricorsiva_like_chain(self):
        out = self._compila_compila_esegui("""
            funzion nummero quad(nummero x) { torn x * x; }
            nummero capo() {
                nummero r = quad(quad(2));
                stambf("%d", r);
                torn 0;
            }
        """)
        self.assertEqual(out.strip(), "16")

    def test_runtime_switch(self):
        out = self._compila_compila_esegui("""
            nummero capo() {
                nummero x = 2;
                facimm (x) {
                    cas 1: stambf("uno"); spacc;
                    cas 2: stambf("due"); spacc;
                    default: stambf("altro");
                }
                torn 0;
            }
        """)
        self.assertEqual(out.strip(), "due")

    def test_runtime_scanef_addizione(self):
        out = self._compila_compila_esegui("""
            nummero capo() {
                nummero a;
                nummero b;
                scanef("%d", &a);
                scanef("%d", &b);
                stambf("%d", a + b);
                torn 0;
            }
        """, stdin="7\n8\n")
        self.assertEqual(out.strip(), "15")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    if not GCC_AVAILABLE:
        print("[ATTENZIONE] gcc non trovato nel PATH: i test di integrazione "
              "end-to-end (incluso il test obbligatorio della calcolatrice) "
              "saranno SALTATI. Installa gcc per eseguirli.\n", file=sys.stderr)
    unittest.main(verbosity=2)
