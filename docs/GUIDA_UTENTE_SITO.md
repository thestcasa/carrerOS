# Guida utente del sito Career OS

Questa guida descrive il sito locale Career OS così come è disponibile e verificato il
10 agosto 2026 su `http://localhost:3000`. I nomi dei pulsanti sono riportati in inglese,
esattamente come compaiono nell'interfaccia.

La prima prova deve usare esclusivamente il candidato fittizio `example_candidate`. Non inserire
dati personali, non usare un ATS reale e non attivare la controlled submission.

## 1. Prima di iniziare: cosa è sicuro provare

Career OS separa analisi, generazione, compilazione sintetica e invio. Il sito non invia nulla
direttamente: solo il backend, dopo i controlli di `SubmissionGate`, può autorizzare un'operazione
finale.

Per una prima prova sicura:

- usa solo `example_candidate` e dati con domini `.invalid`;
- usa il dry run sintetico, che apre la fixture locale su `127.0.0.1:8090` e non fa il click finale;
- non avviare il worker separato di controlled submission;
- non premere `approve controlled submission`;
- non usare `Verify source` su URL di ATS reali durante una prova puramente locale;
- non usare dati reali in CV, job fixture o configurazioni;
- non usare `docker compose down -v`, perché eliminerebbe i volumi persistenti.

Lo stato osservato durante la verifica era il seguente:

- tutti i servizi del Compose risultavano in esecuzione; API, frontend, PostgreSQL e Redis erano
  `healthy`;
- `example_candidate` era il candidato attivo;
- readiness, job, candidature e contatori dipendono dal contenuto persistente del volume locale;
- la modalità corrente era `disabled` e la controlled submission era disabilitata a livello di
  processo;
- `autonomous` resta fail-closed finché non esistono evidenze sintetiche valide e la conferma
  esplicita dell'utente.

## 2. Avviare e arrestare il sito

Apri un terminale WSL e posizionati nella cartella del repository:

```bash
cd /home/thestcasa/code/carrerOS
```

Avvia lo stack completo:

```bash
docker compose up --build
```

Quando i servizi sono pronti, apri:

- sito: `http://localhost:3000`;
- API: `http://localhost:8000`;
- documentazione OpenAPI: `http://localhost:8000/docs`.

Per controllare lo stato senza cambiare dati:

```bash
docker compose ps
```

Lo stack normale comprende `frontend`, `api`, `db`, `redis`, `worker`, `browser-worker` e
`scheduler`. Non comprende il worker di controlled submission.

Se `docker compose up --build` è in primo piano, premi `Ctrl+C` per interromperlo. Per arrestare e
rimuovere i container conservando volumi e dati:

```bash
docker compose down
```

Non aggiungere `-v`. I volumi conservano PostgreSQL, Redis, configurazioni del candidato e artefatti
runtime.

Se una pagina non risponde, esegui prima `docker compose ps`. Riavvia solo i servizi necessari e
non cancellare volumi per correggere un problema di configurazione.

## 3. Orientarsi nell'interfaccia

La barra principale contiene:

- `Overview`: stato generale, salute del runtime e contatori;
- `Candidates`: selezione e creazione del candidato;
- `Jobs`: discovery, filtri e analisi delle offerte;
- `Applications`: pipeline delle candidature;
- `Actions`: interventi umani richiesti;
- `Security`: eventi di sicurezza;
- `Analytics`: indicatori del funnel;
- `Settings`: automazione, ATS, retention ed esportazioni.

In alto compare anche `Active: example_candidate`. Controllalo prima di qualsiasi operazione.

## 4. Selezionare o creare un candidato

### Selezionare `example_candidate`

1. Apri `Candidates`.
2. Individua la scheda `Morgan Example`, con ID `example_candidate`.
3. Premi `Review readiness` per selezionarlo e aprire la readiness, oppure `Edit profile` per
   selezionarlo e aprire direttamente il profilo.
4. Verifica che l'intestazione mostri `Active: example_candidate`.

La selezione è ricordata in un cookie locale. I link operativi propagano comunque il candidato
anche nel parametro `candidate_id`.

### Creare un candidato

La pagina espone i campi `Candidate ID` e `Display name`. L'ID deve iniziare con una lettera
minuscola e può contenere lettere minuscole, numeri e underscore; la lunghezza ammessa è da 3 a 64
caratteri.

Compila entrambi i campi e premi `Create blocked draft`. Il nuovo candidato nasce intenzionalmente
non approvato, con dati fittizi `.invalid`, discovery disabilitata e submission automatica
disabilitata. Deve essere completato e approvato sezione per sezione.

Per la prova descritta in questa guida non creare un secondo candidato: continua con
`example_candidate`.

## 5. Modificare il profilo

Apri `Candidates` e premi `Edit profile`. La pagina `Core profile editor` presenta le sezioni:

`Identity`, `Biography`, `Education`, `Experience`, `Projects`, `Skills`, `Languages`,
`Career strategy`, `Scoring rules`, `Preferences`, `Legal status`, `Approved answers`, `CV rules`,
`Cover letter rules`, `Company rules`, `Role rules`, `Certifications`, `Publications` e
`Notifications`.

Procedura generale:

1. scegli una sezione nella colonna laterale;
2. modifica solo dati fittizi e controlla attentamente le caselle `Approved`;
3. premi `Save new version`;
4. usa `Discard changes` per annullare modifiche locali non salvate;
5. premi `View readiness` e verifica l'effetto sui blocker.

Ogni salvataggio crea una nuova versione della configurazione. Non modifica gli snapshot già usati
da candidature precedenti.

Alcune sezioni hanno campi normali; altre, come `Experience` e `Projects`, espongono gli elementi
come JSON strutturato. Conserva gli ID stabili, non riutilizzarli e non rimuovere i campi di
approvazione, verifica, riservatezza o archiviazione. Un JSON sintatticamente valido può essere
comunque respinto dal backend se viola lo schema.

## 6. Controllare la readiness

Da `Candidates` premi `Review readiness`, oppure usa `View readiness` nell'editor.

La pagina non mostra una percentuale unica. Valuta separatamente:

- `Discovery`;
- `Job analysis`;
- `Document generation`;
- `Assisted form filling`;
- `Controlled submission`;
- `Autonomous submission`;
- `Email tracking`.

Gli stati possibili sono `Ready`, `Ready with warnings`, `Blocked` e `Not configured`. Nella sezione
`Profile domains`, i link `Edit domain →` portano alla parte del profilo che può risolvere il
problema.

Nello stack verificato, `example_candidate` era `Valid` come schema ma non `ready`: mancavano
approvazioni per identità, biografia, skills, strategia, preferenze, stato legale e regole documenti;
mancavano inoltre una lingua approvata, la data di disponibilità e la verifica dello stato legale.
`Valid` significa quindi soltanto “leggibile e conforme allo schema”, non “autorizzato a operare”.

### Attenzione ai volumi persistenti non aggiornati

Il volume Docker `candidate_data` può mascherare una fixture più recente presente nel repository.
Se il sito mostra blocker inattesi:

```bash
docker compose exec -T api \
  python -m app validate-candidate --candidate example_candidate
docker compose exec -T api \
  python -m app readiness --candidate example_candidate
```

Non usare `docker compose down -v` e non sovrascrivere candidati privati. Per ispezionare il
confronto non distruttivo con la fixture inclusa nell'immagine:

```bash
docker compose exec -T api python -m app inspect-candidate-volume
```

Per ottenere una copia da revisionare, senza modificare il volume attivo:

```bash
docker compose exec -T api python -m app stage-candidate-recovery \
  --destination-root /app/runtime/recovery-review
```

Il comando rifiuta ID non sicuri, symlink e destinazioni già occupate o interne alla sorgente.
Consulta `docs/OPERATIONS.md` prima di sostituire qualunque configurazione persistente.

## 7. Importare un CV TXT, PDF o DOCX

Nella parte alta del `Core profile editor` trovi `Import a CV draft`.

Sono supportati `.txt` UTF-8, `.pdf` e `.docx`. Il backend limita il file a 2 MiB, calcola l'hash
SHA-256 e non conserva l'originale. PDF cifrati, con contenuto attivo, troppi oggetti/stream,
compressione eccessiva o più di 50 pagine vengono rifiutati; DOCX con contenuto espanso eccessivo
vengono rifiutati. Il testo estratto resta soggetto ai limiti di righe e caratteri.

Il parser riconosce righe separate da `|` sotto le intestazioni `EDUCATION` e `EXPERIENCE`.
Esempio completamente fittizio:

```text
EDUCATION
Example University | MSc | Computer Science | Exampleton | 2020-09 | 2022-06

EXPERIENCE
Fictional Robotics Ltd | ML Engineer | Remote | 2022-07 | present | Python, SQL
- Built a deterministic fictional evaluation pipeline.
```

Procedura:

1. premi il selettore `CV file` e scegli un `.txt`, `.pdf` o `.docx`;
2. premi `Extract unapproved draft`;
3. controlla il numero di elementi rilevati e tutti i warning;
4. premi `Apply as unapproved facts` solo se vuoi aggiungere davvero quei dati al profilo;
5. apri `Education` ed `Experience`, correggi ogni campo e approva esplicitamente i fatti ammessi;
6. torna a `View readiness`.

L'estrazione da sola non applica nulla. L'applicazione del draft crea una nuova versione, ma tutti i
fatti importati restano `restricted`, non verificati e non approvati: è normale che la readiness
resti bloccata.

## 8. Scoprire e filtrare le offerte

Apri `Jobs`. La pagina ha due aree: `Run discovery` e `Jobs inbox`.

### Import manuale per sviluppo

`Manual fixture import` permette di incollare un array JSON prodotto da un adapter o da una fixture
deterministica. Seleziona `Greenhouse`, `Lever` o `Ashby`, incolla i dati in `Structured payloads` e
premi `Run discovery`.

Un payload Greenhouse minimo e fittizio è:

```json
[
  {
    "id": 101,
    "internal_job_id": 7,
    "title": "ML Engineer",
    "content": "<p>Build truthful fictional models.</p>",
    "location": {"name": "Remote"},
    "absolute_url": "https://boards.greenhouse.io/fictional/jobs/101"
  }
]
```

Questo import è un percorso di sviluppo, non una prova che l'offerta esista ancora. Non usare
`Verify source` con questa fixture: la verifica fresca prova a contattare il feed ufficiale.

### Sorgenti pianificate

Per `Scheduled sources`, compila `ATS platform`, `Company`, `Official company domain`,
`Public board token` e `Cadence minutes`, quindi premi `Schedule source`. Il pulsante resta
disabilitato finché i campi obbligatori non sono validi.

Prima devi aprire `Settings`, attivare `Enable read-only scheduled discovery` e consentire
l'adapter necessario. Questa funzione contatta endpoint ATS pubblici e va quindi usata solo quando
si intende davvero leggere quella sorgente.

### Filtri disponibili

Nell'inbox sono realmente disponibili:

- `Search jobs`;
- `Role category`: `All categories`, `Configured target`, `Configured adjacent`, `Non-target`;
- `Inbox state`: `All states`, `Discovered`, `Saved`, `Ignored`, `Blocked`, `Shortlisted`;
- `Hard blockers only`.

Quando non ci sono risultati compare `No jobs match these filters`. Cambiare i filtri non modifica
lo stato dei job.

### Valutare un'offerta

Apri una scheda job con `Review analysis →`. Il dettaglio mostra score, classificazione, confidence,
azione proposta, source freshness, descrizione originale e normalizzata, requisiti, salary evidence,
dimensioni del punteggio, bonus, penalità, esperienza/progetti selezionati e security findings.

Le azioni disponibili nel dettaglio sono:

- `Verify source`: rilegge la sorgente ufficiale;
- `Shortlist`: salva il job nella shortlist;
- `Skip job`: lo marca come ignorato;
- `Generate materials`: crea la candidatura e i materiali solo se esistono score e prerequisiti.

Queste azioni non autorizzano un invio. `Generate materials` è disabilitato in presenza di hard
blocker e il backend può comunque negare l'operazione se readiness o verifica fresca non passano.

## 9. Generare e revisionare CV, cover letter e risposte

Da un job idoneo premi `Generate materials`. Il sito crea un'applicazione e apre il relativo
dettaglio.

La pagina mostra la `Role-aware material policy`, inclusi template, versione del job, esperienze e
progetti selezionati e motivazione per includere o omettere la cover letter.

### CV e cover letter

In `Draft editor`:

1. scegli la versione in `Document versions`;
2. controlla `Claim provenance` e `Render and independent review`;
3. premi `Edit selected draft`;
4. modifica solo l'heading canonico e bullet già sostenuti da fatti approvati;
5. aggiungi, se utile, `Revision reason (optional)`;
6. premi `Save as new version`, oppure `Cancel editing`.

Il salvataggio aggiunge una versione e riesegue validazione, rendering PDF e review indipendente.
Le versioni precedenti diventano `Immutable history` e non vengono sovrascritte.

### Risposte alle domande

In `Application questions`, usa `Edit latest answer`, modifica `Answer content`, aggiungi
eventualmente `Revision reason (optional)` e premi `Save as new answer version`. Usa
`Cancel answer edit` per annullare.

Anche le risposte sono append-only. Il backend ricalcola provenance e supporto; una risposta libera
non coincidente con una risposta approvata può restare `Blocked`.

## 10. Usare la pipeline e il dry run sintetico

Apri `Applications`. In assenza di dati compare `No applications yet`. Una candidatura nasce da
`Generate materials`, non da un inserimento manuale in questa pagina.

Ogni scheda mostra azienda, ruolo, score, stato, ultimo evento e `Next`. Premi `Open application`.
Nel dettaglio compare un solo pulsante primario coerente con lo stato:

1. `approve materials` quando la review è in attesa;
2. `start` quando i materiali approvati possono entrare nel flusso;
3. `dry run` durante `form_filling`;
4. `authorize submit` quando lo stato è `ready_to_submit` e la controlled submission è disabilitata;
5. `approve controlled submission` solo quando il processo separato di controlled submission è
   stato esplicitamente abilitato.

Per la prima prova fermati dopo `dry run`. Il `browser-worker` usa la fixture locale, compila solo
campi noti, carica soltanto il PDF con hash atteso, acquisisce PNG/HTML/manifest e registra
`submit_clicked=false`. La pagina effettua polling dello stato durevole mentre il worker lavora.

Non premere `authorize submit` durante una semplice ispezione. Con l'impostazione standard il
pulsante porta a una conferma sintetica, non a un ATS reale, ma crea comunque autorizzazione,
archivi ed eventi persistenti. Non premere mai `approve controlled submission` in questo ambiente.

Il viewer `Exact backend-confirmed submission` mostra CV, cover letter, risposte e receipt solo dopo
una conferma backend. I PDF sono scaricati con `Download exact PDF`; JSON e HTML sono mostrati come
testo inerte con `Preview escaped text`. Gli altri artefatti espongono `Download exact artifact`.

## 11. Gestire le Human actions

Apri `Actions`. Lo stato vuoto è `No intervention required`.

Quando un dry run incontra CAPTCHA, OTP, domanda sensibile, ambiguità legale o errore di selettore,
compare una scheda con motivo, scadenza, screenshot, salute della sessione e conseguenze. I pulsanti
possibili sono:

- `Open evidence screenshot`;
- `Record local takeover handshake`;
- `Confirm human action complete`;
- `Cancel and withdraw`.

`Record local takeover handshake` registra soltanto un handshake autenticato. Nella build attuale
non apre né controlla davvero la sessione browser: il trasporto interattivo sicuro è ancora
`unavailable`. Non dichiarare l'azione completata finché il verifier della stessa sessione non può
confermarla. Career OS non risolve né aggira CAPTCHA o OTP.

## 12. Eventi di sicurezza

Apri `Security`. Lo stato vuoto è `No security events`.

La pagina elenca prompt injection, redirect bloccati, accessi file negati e decisioni di submission
bloccate, con severity e dettaglio. `Resolve event` marca un evento come risolto e scrive un audit:
usalo solo dopo aver verificato davvero la causa. Risolvere l'evento non indebolisce automaticamente
gli altri blocker.

## 13. Analytics

Apri `Analytics`. La pagina osservata mostra:

- numero di `Applications`;
- `Average score`;
- numero di `Confirmed`;
- `By state`;
- `By role category`;
- human actions pendenti e security events irrisolti.

Con un database vuoto i contatori sono zero. Le analytics sono candidate-scoped e misurano risultati
confermati dal backend.

## 14. Settings e automazione

Apri `Settings`. Le modalità visibili sono `disabled`, `dry run`, `approval required` e
`autonomous`.

- `disabled`: nessuna automazione operativa;
- `dry run`: percorso sintetico senza invio reale;
- `approval required`: richiede una decisione esplicita prima della fase controllata;
- `autonomous`: può essere selezionata solo senza blocker.

Se `autonomous` è disabilitato, le schede mostrano in linguaggio semplice l'evidenza mancante e
l'azione sicura successiva. L'accettazione dell'adapter e del dry run deriva soltanto da prove
sintetiche riuscite e persistite; la conferma autonoma è separata, inizialmente non selezionata e
auditata. Non tentare di impostare queste evidenze direttamente tramite API.

Altri controlli:

- `Enable read-only scheduled discovery` abilita o sospende la pianificazione;
- le caselle `greenhouse`, `lever` e `ashby` definiscono gli adapter consentiti, non quelli già
  testati;
- `Confirmed browser-session retention` accetta da 1 a 3650 giorni; conferma con `Save retention`;
- `Activate emergency stop` richiede una conferma del browser e blocca subito nuove autorizzazioni.

La UI corrente non offre un pulsante per disattivare l'emergency stop. Non provarlo come semplice
test: è un controllo persistente e intenzionale.

I limiti giornalieri, settimanali e per azienda sono mostrati, ma in questa pagina non sono
modificabili. Gli archivi submitted restano conservati fino a una cancellazione intenzionale del
candidato.

## 15. Esportare e importare configurazioni e dati

In fondo a `Settings` ci sono due percorsi distinti.

### Solo configurazione

- `Download configuration JSON` scarica la configurazione sorgente in JSON;
- `Download configuration YAML` scarica la stessa configurazione in YAML;
- seleziona un file nel campo `Configuration bundle (.json, .yaml, or .yml; maximum 1 MiB)`;
- premi `Import configuration`.

Il bundle deve appartenere allo stesso candidate ID, essere UTF-8 e non superare 1 MiB. L'import
sostituisce tutte le sezioni insieme, valida la versione attesa e crea al massimo una nuova versione.
Non ripristina workflow, job, candidature, browser state, archivi, segreti o deletion state. Gli
switch operativi locali restano locali.

### Esportazione completa

`Download candidate export` produce un JSON portabile con configurazione e storico, record del
workflow, evidenze job condivise usate dal candidato e byte esatti degli archivi. Credenziali del
browser, token segreti e percorsi locali sensibili sono esclusi.

`example_candidate` è protetto dalla cancellazione e non mostra il comando distruttivo. Per gli
altri candidati la UI richiede di digitare esattamente l'ID prima di abilitare
`Delete candidate and archives`. La cancellazione è irreversibile; questa guida non richiede né
autorizza di provarla.

## 16. Stati vuoti ed errori

Gli stati vuoti verificati sono espliciti:

- Jobs: `No jobs match these filters`;
- Applications: `No applications yet`;
- Actions: `No intervention required`;
- Security: `No security events`;
- materiali: `No material drafts`;
- artefatti submitted: `No immutable submitted artifact is recorded`.

Aprendo un job o un'applicazione inesistente, il sito mostra `We could not load this view.` e
`Request data did not match the API contract.`. Nel dettaglio applicazione è disponibile
`Try again`. Gli errori di azione restano fail-closed e non fanno avanzare ottimisticamente lo stato.

## 17. Funzioni disponibili, limitate o incomplete

| Area | Stato reale della build verificata |
| --- | --- |
| Avvio locale | Funzionante con un solo `docker compose up --build`; stack attualmente operativo. |
| Candidati | Selezione, creazione di draft bloccati, editor e versioning disponibili. Molte sezioni usano JSON tecnico. |
| Readiness | Funzionante e separata per capability; lo stato persistito di `example_candidate` è attualmente bloccato. |
| Import CV | TXT UTF-8, PDF e DOCX con limiti fail-closed; l'estrazione crea solo fatti non approvati. |
| Discovery | Import fixture e configurazione Greenhouse/Lever/Ashby disponibili; gli altri ATS citati nella specifica non sono implementati. |
| Filtri job | Disponibili ricerca, categoria, stato e hard blocker; i filtri più ricchi previsti dalla specifica non sono presenti. |
| Materiali | Generazione, PDF versionati, provenance, review ed editing append-only sono implementati; richiedono un job e un profilo pronti. |
| Pipeline | Vista a schede e dettaglio disponibili; non esiste ancora la board/list view completa prevista dalla specifica. |
| Dry run | Implementato tramite fixture Playwright locale e worker isolato; lo stato corrente non consente di raggiungerlo senza risolvere readiness e creare un'applicazione valida. |
| Controlled submission | Codice presente ma worker assente dal Compose normale e funzione disabilitata a livello di processo. Non adatta a questa prova. |
| Autonomous mode | Percorso guidato ed evidenze sintetiche implementati; resta disabilitato finché test esatti e conferma esplicita non sono validi. |
| Human takeover | Evidenze, scadenza, annullamento e handshake disponibili; trasporto interattivo verso la stessa sessione non implementato. |
| Security | Ledger e risoluzione disponibili; nello stato verificato non c'erano eventi. |
| Analytics | Contatori base per stato e categoria disponibili; metriche avanzate per ATS, CV, salary e conversione non presenti. |
| Corrispondenza | Fondazioni e viste nel dettaglio applicazione presenti; ingestione Gmail/OAuth reale non disponibile. |
| Hosted deployment | Identity provider, storage cifrato e broker di takeover sicuro non completati. L'app è locale e single-user. |
| Uso reale | Non pronto: non abilitare controlled submission o autonomia e non usare dati personali finché sicurezza, test browser e integrazioni esterne non sono completati e revisionati. |

La pipeline guidata, le evidenze di autonomia, lo scheduler ricorrente e le suite browser sono
implementati e verificati. Restano esterni alla build locale il pilot con dati privati, la revisione
del provider reale, Gmail OAuth/secret storage e un broker sicuro per il takeover interattivo della
stessa sessione.

## 18. Percorso consigliato per la prima prova

Questo percorso evita ATS e invii reali.

1. Avvia `docker compose up --build` e controlla `docker compose ps`.
2. Apri `http://localhost:3000` e verifica `Live submission: Blocked`.
3. Apri `Candidates`, scegli `example_candidate` con `Review readiness` e non creare altri profili.
4. Leggi tutti i blocker. Se sembrano incoerenti con la fixture del repository, verifica il volume
   con i comandi CLI della sezione 6; non cancellarlo.
5. Apri `Edit profile` e familiarizza con le sezioni senza salvare dati personali. Per una prova di
   import, usa un TXT/PDF/DOCX fittizio e fermati dopo `Extract unapproved draft`; premi
   `Apply as unapproved facts` solo se vuoi modificare davvero il profilo demo.
6. Apri `Jobs`. Prova i filtri sullo stato vuoto. Se vuoi testare la normalizzazione, usa il payload
   fittizio della sezione 8 e `Run discovery`, senza `Verify source`.
7. Apri `Applications`, `Actions`, `Security` e `Analytics` per riconoscere gli stati vuoti.
8. Apri `Settings`: controlla che `autonomous` sia disabilitato e che il testo dica
   `Live controlled submission is disabled at the process boundary.` Non cambiare modalità e non
   attivare `Activate emergency stop` durante la sola ispezione.
9. Prova, se necessario, soltanto i download `Download configuration JSON` o
   `Download configuration YAML`; non reimportare un bundle non revisionato.
10. Per un dry run end-to-end, prepara prima un profilo fittizio realmente ready e un job con prova
    di sorgente controllata in un ambiente di test. Segui poi `Generate materials` →
    `approve materials` → `start` → `dry run` e fermati prima di `authorize submit`.
11. Al termine, arresta con `Ctrl+C` e `docker compose down`, senza `-v`.

Questo percorso verifica l'interfaccia e i confini di sicurezza senza candidatura reale, senza
controlled submission, senza ATS reale e senza dati personali.
