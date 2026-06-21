# Compilatore C-ro

Compilatore per il linguaggio **C-ro**, un sottoinsieme del linguaggio C con
parole chiave ispirate al dialetto napoletano, sviluppato per il corso di
*Elementi di Ingegneria dei Linguaggi di Programmazione* (A.A. 2025/26,
Prof. G. Costagliola) — **Progetto A: compilatore completo**.

Il codice sorgente C-ro viene tradotto in codice **C standard**, compilabile
con qualsiasi compilatore C conforme (es. `gcc`).

## Architettura

```
Sorgente .cro
     │
     ▼
Lexer + Parser (Lark, algoritmo Earley)
     │
     ▼
AST  (dataclass Python)
     │
     ▼
Analisi Semantica (scoping con stack di tabelle dei simboli + type checking)
     │
     ▼
Generatore di Codice (Visitor con riflessione)
     │
     ▼
Codice C standard
```

Tutte le fasi sono implementate in un unico file, `compilatore_cro.py`,
suddiviso in sezioni numerate (grammatica, nodi AST, transformer, analisi
semantica, generatore di codice, pipeline, self-test, CLI). Per la
descrizione dettagliata delle specifiche del linguaggio e delle scelte
implementative, vedere la documentazione tecnica allegata.

## File del progetto

| File                  | Contenuto                                                        |
|------------------------|-------------------------------------------------------------------|
| `compilatore_cro.py`   | Il compilatore completo (lexer, parser, AST, semantica, codegen) |
| `calcolatrice.cro`     | Programma di esempio/test obbligatorio: calcolatrice a menu      |
| `test_suite.py`        | Suite di test automatizzati (43 test, unitari + integrazione)    |

## Dipendenze

- **Python 3.10+**
- **Lark** (parsing toolkit):
  ```bash
  pip install lark
  ```
- **gcc** (opzionale ma raccomandato): necessario per compilare ed eseguire
  il codice C prodotto, e per eseguire i test di integrazione end-to-end
  della suite di test. Senza `gcc` il compilatore funziona comunque (produce
  comunque il file `.c`), ma quei test specifici vengono saltati.

  - **Linux**: generalmente già presente, altrimenti `sudo apt install gcc`.
  - **macOS**: `xcode-select --install`.
  - **Windows**: installare MinGW-w64 (es. tramite [MSYS2](https://www.msys2.org/))
    e aggiungere `gcc` al PATH, oppure usare WSL.

## Installazione

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install lark
```

## Uso

### Compilare un sorgente C-ro

```bash
python compilatore_cro.py sorgente.cro                # stampa il C su stdout
python compilatore_cro.py sorgente.cro -o sorgente.c   # scrive su file
```

### Compilare ed eseguire l'output

```bash
gcc -Wall -Wextra -o sorgente sorgente.c
./sorgente
```

### Eseguire i test

Self-test rapido integrato nel compilatore (10 casi):
```bash
python compilatore_cro.py --self-test
```

Suite di test completa (43 test: 35 unitari sui singoli costrutti del
linguaggio + 8 di integrazione end-to-end che compilano ed eseguono
realmente il C generato con `gcc`, incluso il test obbligatorio della
calcolatrice):
```bash
python test_suite.py -v
```

## Esempio rapido

Salva come `esempio.cro`:

```
funzion nummero doppio(nummero x) {
    torn x + x;
}

nummero capo() {
    nummero n = 5;
    stambf("Il doppio di %d e' %d\n", n, doppio(n));
    torn 0;
}
```

Compila ed esegui:

```bash
python compilatore_cro.py esempio.cro -o esempio.c
gcc -Wall -Wextra -o esempio esempio.c
./esempio
```

Output atteso: `Il doppio di 5 e' 10`

## Programma dimostrativo: calcolatrice

`calcolatrice.cro` è il programma di test obbligatorio richiesto dalla
traccia d'esame: un menu interattivo per le quattro operazioni aritmetiche
di base, con lettura di input (interi e reali), gestione della divisione
per zero, e ciclo di continuazione/uscita gestito dall'utente. Esercita
quasi tutti i costrutti del linguaggio (funzioni, `if`/`S'invece`/`else`,
`facimm`/`cas`/`default`, `trament`, `const`, operatori logici e
relazionali, `scanef`/`stambf`).

```bash
python compilatore_cro.py calcolatrice.cro -o calcolatrice.c
gcc -Wall -Wextra -o calcolatrice calcolatrice.c
./calcolatrice
```

## Limitazioni note

- Il linguaggio non supporta array, puntatori generici (a parte l'operatore
  `&` usato esclusivamente per `scanef`), struct, o gestione della memoria
  dinamica.
- I tipi di ritorno multipli (presenti in altri linguaggi del corso, es.
  Toy2) non sono supportati: ogni funzione restituisce un solo valore,
  coerentemente con la semantica del C.
- Per i dettagli completi sulle scelte progettuali e sulle eventuali
  deviazioni rispetto alle specifiche originali del linguaggio, vedere la
  documentazione tecnica.
