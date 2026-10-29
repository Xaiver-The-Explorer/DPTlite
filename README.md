# DPTlite — DNA Protein Toolbox (light version)

A small Flask web app for CS50 final project. It auto-detects **DNA**, **RNA**, or **protein** input, translates nucleic acids into protein,
and runs a set of **simple, heuristic** structure predictions — now wrapped in accounts, history, bookmarking, and a small API-key system.

**One‑click powerful analyses**
- Overview of input sequence with all kinds of information (type, length, composition, molecular weight, theoretical pI, etc.)
- Translation using the standard genetic code (6-frame translation + simple ORFs finder)
- Kyte–Doolittle hydrophobicity plot and net charge distribution (both are sliding windows)
- Protein secondary structure prediction (based on Chou–Fasman conformational propensities)
- Domain style calls: transmembrane helices, signal peptide, and an order/disorder prediction (based on Uversky charge–hydropathy rule)

**Various convenient features**
- Customize sequence name and save interested sequence as a bookmark
- Export outcomes as downloadable reports (.txt, .json, .pdf, .fasta, .zip) and generate static plots as PNG images (matplotlib)
- Review and reload your history in the last 30 days
- Access user data and edit bookmark in your profile
- Create an API key for advanced use in your profile

> [!IMPORTANT]
> **These are bioinformatic heuristics, not lab-grade predictions.**
> They make the underlying principles of biology visible, but they don't replace TMHMM, PSIPRED, or IUPred.


## Tips before reading

*Prerequisites* - some basic STEM knowledge is assumed, including: college-level introductory biology, and college-level general chemistry.

*Settings* - all Markdown Documents are optimized for 14 inches or larger screens. Recommend to turn off **Word Warp** in VS Code settings.


## How to use this app

DPTlite is designed as a "next generation's online toolkit" which is comprehensive but easy to use. The opreations are very simple: register
an account, then log in to use advanced analytic tools freely. Users can upload files, download reports, and customize their own sequences.

See the **video demo** on YouTube for more details: [DPTlite User Manual](https://www.youtube.com)


## What's in this project

### Pages (in `templates`)

| Page     | Route       | Notes                                                           |
|----------|-------------|-----------------------------------------------------------------|
| Home     | `/`         | Hero section over an original SVG DNA double-helix background   |
| Register | `/register` | name, email, password, confirm password                         |
| Login    | `/login`    | email + password                                                |
| Analysis | `/analysis` | **Login required.** The DNA/RNA/protein sequence tool (*core*)  |
| History  | `/history`  | **Login required.** Your analyses from the last 30 days         |
| Profile  | `/user`     | **Login required.** Usage stats, API key, bookmarks             |
| Donate   | `/donate`   | Public. Placeholder — no real payment processing for now        |
| About    | `/about`    | Public. Mission statement + contact email address               |

All pages extend `templates/layout.html`, which has the DPTlite brand top-left, a nav bar, a light/dark toggle (light is the default), and
a footer. With the help of `static/script.js` and `static/bookmarks.js`, users can interact with some contents on certain pages.


### Functions (in `biology.py`)

| Function                                     | Feature                                                               |
|----------------------------------------------|-----------------------------------------------------------------------|
| `clean_sequence_data`                        | Strip FASTA headers, whitespace, and digits; uppercase the rest       |
| `detect_sequence_type`                       | Work out whether the cleaned sequence looks like DNA, RNA, or protein |
| `to_dna`, `transcribe`, `reverse_complement` | Swap RNA to DNA, coding-strand transcription, reverse complement      |
| `translate_frame`, `six_frame_translation`   | Codon translation, build all 3 forward + 3 reverse reading frames     |
| `find_orfs`                                  | Scan every frame for ATG...STOP open reading frames, longest first    |
| `gc_content`, `base_composition`             | Calculation for GC content and base composition of the sequence       |
| `clean_protein`                              | Drop stop-codon markers and unknowns so downstream math stays clean   |
| `amino_acid_composition`, `molecular_weight` | Calculation for amino acid composition and molecular weight           |
| `net_charge_at_ph`                           | Henderson-Hasselbalch net charge of the protein at a given pH         |
| `estimate_pi`                                | Binary-search the pH where net charge crosses zero (theoretical pI)   |
| `sliding_window_profile`                     | One value per residue position, same length as the protein            |
| `charge_profile`, `hydropathy_profile`       | Charge distribution and hydrophobicity plot (Kyte–Doolittle scale)    |
| `predict_secondary_structure`                | Chou-Fasman style secondary structure prediction for helix/sheet/turn |
| `structure_summary`                          | Calculation for the percentage of helix/sheet/turn in the structure   |
| `predict_transmembrane_helices`              | Transmembrane helix prediction (classic hydropathy-plot approach)     |
| `predict_signal_peptide`                     | Signal peptide prediction (classic h-region approach)                 |
| `predict_order_disorder`                     | Order/disorder prediction (simplified Uversky charge-hydropathy plot) |
| `disorder_profile`                           | Positional order/disorder tendency along the sequence                 |
| `analyze_protein`                            | Bundle every protein-level analysis into one JSON-friendly dictionary |


### Backend Features (in `app.py`)

01. **Rate limiting** — a small in-memory sliding-window limiter (no extra service needed) on login/register/analyze/plots to blunt spam or
    a runaway loop. Exceeding it returns HTTP 429 (JSON) or a flashed message on HTML pages.

02. **Input length limit** — sequences over 50,000 letters are rejected with a clear error instead of freezing the server.

03. **Caching** — identical cleaned sequences return a cached result instantly (`"from_cache": true` in the response) instead of recomputing.
    Capped at 300 entries, oldest evicted first.

04. **Error handling** — a global handler turns unexpected exception or HTTP error (404, 405, etc.) into JSON instead of a stack trace page.

05. **FASTA upload** — handled entirely client-side: a file input reads the `.fasta`/`.fa`/`.txt` file into the textarea via `FileReader`, so
    no new upload route was needed.

06. **Downloadable report** — `/api/report` regenerates the analysis and returns a summary file (multiple formats available, including `.txt`,
    `.json`, `.pdf`, `.fasta`, and `.zip`) as an attachment.

07. **Protein visualization (matplotlib)** — `/api/plots` renders a hydropathy plot, a charge-vs-pH curve, and a disorder-tendency curve as
    PNGs (via the non-interactive `Agg` backend, base64-encoded, no files written to disk).

08. **Sequence bookmarking** — save a sequence under a custom name (`/api/bookmarks`), reload or delete it later, from the Analysis page or
    your Profile. Besides, as newest supplements, more features (sort, group, and rename) are available in the updated bookmark system.

09. **Light/dark mode** — light is the default; the toggle top-right persists your choice in `localStorage`.

10. **API key system** — each account gets a key (shown on `/user`, regenerate any time). `/api/v1/analyze` accepts it via the `X-API-Key`
    header for scripted/programmatic use, no cookies needed.

11. **Interactive charts** — Chart.js line charts for hydropathy, charge, and disorder, plus a small bar chart summarizing the secondary
    structure mix.

12. **Invalid-character highlighting** — the live sequence preview marks any character outside the expected alphabet in red as you type.


### Data Storage (in `dptlite.db`)

Plain `sqlite3` library, one file: `dptlite.db`, created automatically on first run. Three tables: `users`, `history`, `bookmarks`.


## Project Layout

```
project/
├── app.py                      # routes only -- Flask setup + every @app.route
├── benchmarks.py               # sanity check for the order/disorder predictor & transmembrane helix predictor
├── biology.py                  # the science: reference data + pure sequence/protein math
├── helpers.py                  # the plumbing: DB, auth, rate limiting, cache, plots, reports
├── LICENSE.md                  # MIT License
├── README.md                   # description and explanation of project
├── requirements.txt            # Flask + matplotlib
├── dptlite.db                  # created automatically on first run (sqlite3)
├── templates/
│   ├── layout.html             # shared header/nav/theme-toggle/footer
│   ├── index.html              # homepage
│   ├── register.html           # new user register
│   ├── login.html              # user login
│   ├── analysis.html           # the DNA/RNA/protein sequence tool (login required)
│   ├── history.html            # history in the last 30 days (login required)
│   ├── user.html               # profile / stats / API key / bookmark (login required)
│   ├── donate.html             # make a donation
│   └── about.html              # mission statement + contact email
└── static/
    ├── style.css               # light (default) + dark theme via [data-theme]
    ├── script.js               # analysis.html logic (charts, uploads, etc.)
    ├── bookmarks.js            # user.html bookmark system manager
    ├── theme.js                # light/dark toggle, shared on every page
    └── images/dna-helix.svg    # original vector DNA graphic
```


### File Segmentation

Why four Python files instead of one?

This mirrors the `app.py` + `helpers.py` split from CS50's own Finance problem set, with `biology.py` added alongside for the actual science,
and `benchmarks.py` for developing and testing purposes.

- **`biology.py`** — pure functions and reference tables (the genetic code, Kyte-Doolittle scale, Chou-Fasman propensities, etc.). Nothing in
  here imports Flask; it just takes a string in and returns a number/string/dictionary. This is the core part of CS50 final project.

- **`benchmarks.py`** - a sanity check for the order/disorder predictor and transmembrane helix predictor in biology.py (both had bugs during
  development). Each benchmark protein used here has a well-known behaviour in the lab. All sequences were typed from UniProt entries.

- **`helpers.py`** — the database, `login_required`/`api_key_required` decorators, the rate limiter, the results cache, matplotlib rendering,
  and report formatting. `app.py` imports what it needs by name, e.g.:
  ```python
  from biology import clean_sequence_data
  from helpers import login_required, api_key_required, rate_limit, run_full_analysis, ...
  ```

- **`app.py`** — just Flask configuration, the two error handlers, and every `@app.route`. At a glance you can see the whole site map without
  wading through biology or infrastructure code.

> [!NOTE]
> A large number of comments are inserted into these Python files intentionally so as to help understanding. Recommend to read them thoroughly.


## Homepage Background

The homepage background is an **original SVG** generated with a short script (two sine-wave "strands" with connecting rungs) rather than a
downloaded photo — this keeps things copyright-clean and, since it's a vector, it stays perfectly crisp at any screen size or resolution.


## API Example

```bash
curl -X POST http://localhost:5000/api/v1/analyze \
  -H "X-API-Key: <your key from the Profile page>" \
  -H "Content-Type: application/json" \
  -d '{"sequence": "ATGGCTAAACTGTAA"}'
```


## AI Usage

The inline suggestions of Github Copilot (free) were used to improve project design during the development. No credits were used.


## License

This project is licensed under the MIT License – see the `LICENSE.md` for details.


## Reference

| Type     | Name                                                     | Notes                                                                        |
|----------|----------------------------------------------------------|------------------------------------------------------------------------------|
| Textbook | Lehninger Principles of Biochemistry, 8th Edition        | David L. Nelson, Michael M. Cox, Aaron Hoskins. © 2021 Macmillan Learning    |
| Textbook | Campbell Biology, 12th Edition                           | Lisa A. Urry, Michael L. Cain, Peter V. Minorsky. © 2021 Pearson Education   |
| Course   | 7.00x Introduction to Biology: The Secret of Life        | Taught by Eric S. Lander, MIT Department of Biology. Provided by MITx        |
| Course   | MCB63X Principles of Biochemistry                        | Taught by Alain Viel, Harvard Faculty of Arts & Sciences. Provided by edX    |
| Course   | Introduction to Genetics and Evolution                   | Taught by Mohamed Noor, Duke Department of Biology. Provided by Coursera     |
| Course   | CS50X Introduction to Computer Science                   | Taught by David J. Malan, Harvard School of Engineering and Applied Sciences |
| Website  | [ToolsRail](https://www.toolsrail.com/biology-tools.php) | A comprehensive collection of essential biology tools to streamline workflow |
| Website  | [bioinformatics.tools](https://bioinformatics.tools)     | Bioinformatics tools for sequence analysis, cloning and assay data           |
| Website  | [Bioinfo Tools Hub](https://biotoolshub.org)             | Bioinformatics tools hub for DNA, RNA and protein analysis                   |
| Website  | [Biopython](https://biopython.org)                       | A set of freely available tools for biological computation written in Python |
| Website  | [Bootstrap](https://getbootstrap.com)                    | The most popular HTML, CSS, and JavaScript library in the world              |


## Acknowledgment

As a one-person CS50 final project, the design and development (including numerous version updates and bug fixes) took more than 3 months.

The progress was slow, tough, and exhausting. However, the achievement is remarkable. This is the victory of passion and determination.

The appreciation should be expressed to the following institutions that gave the author an opportunity to turn his inspiration into reality:
- Harvard University
- Massachusetts Institute of Technology

Special thanks to the beloved professors: Eric S. Lander, David J. Malan, Mohamed Noor, Alain Viel, and all the support staff.


## Contact

- **Author**: Xuan He (also known as *Hex-The-Observer* or *Xavier-The-Explorer*)
- **GitHub**: [Xavier-The-Explorer](https://github.com/Xavier-The-Explorer)
- **LinkedIn**: [Xuan He](https://www.linkedin.com/in/hex-the-observer)
- **Email**: heseelion@gmail.com

This project will be maintained after the end of CS50X 2026 and thus become an open source repository on GitHub for freely use and download.

If you have any questions or suggestions, please contact the author through support channels mentioned above. Thanks for reading! :smile:


© 2026 Hex-The-Observer · MIT Licensed. All rights reserved.
