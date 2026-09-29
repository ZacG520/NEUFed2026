Northeastern's 2026 Fed Challenge team git repo for data viz code.

# Setup (once)
0. Have Python 3.11+ and an IDE (VS Code recommended) installed on your computer, plus Google Chrome (used to save PNGs).

1. Clone this repo (the green "Code" button on GitHub gives you the url, the command is "git clone <URL>")

2. Open a terminal in the NEUFed2026 folder, create a virtual environment, and install the packages:
   - Mac: `python3 -m venv .venv`, then `source .venv/bin/activate`, then `pip install -r requirements.txt`
   - Windows: `python -m venv .venv`, then `.venv\Scripts\activate`, then `pip install -r requirements.txt`

3. Go to https://fred.stlouisfed.org/ and make an account. Once you've done that click on the profile icon. Click "API Keys" and then request an API Key for personal use (delivery should be instantenous). Copy and paste the API key into the .txt file at "fred_api_key.txt" (in the NEUFed2026 folder). Don't leave any spaces or extra text

4. In VS Code, choose the `.venv` Python interpreter/kernel when it asks (or click the kernel name at the top right of a notebook).

# Make a graph (quick way)
Open **`make_graph.ipynb`** in the NEUFed2026 folder.

1. Run the **Setup** cell once.
2. Fill in the **Settings** cell: where the data comes from, the chart type, the title, and formatting options. Every option has a comment explaining it.
3. Run **Settings → Load data → Make graph**. The PNG is saved to `figures/png/` and shown in the notebook.
4. To make another graph, change the settings and re-run those three cells.

**Data sources**
- **FRED:** type series IDs, like `"CPIAUCSL, CPILFESL"`, or `{"Headline CPI": "CPIAUCSL"}` to name the lines yourself. The ID is the code at the end of a FRED page's URL.
- **Several sources at once:** use a list, like `["umich_1y.csv", "umich5y.csv", {"Core PCE": "PCEPILFE"}]`. Dates are lined up automatically, and repeated column names get the file name added, e.g. `Median (umich5y)`.
- **Excel / CSV:** put the file in `DATA2026/` and type its name, like `"NFCI.csv"`. (Files in the older `code/data/` folder are found too.) Title rows, footnotes, odd date formats (`202301`, `2023Q1`, separate Year/Quarter columns) and `na` values are handled automatically. The Load data cell prints what it detected so you can check it.

**Chart types:** `line`, `contribution` (stacked bars with a total line, e.g. GDP contributions), `bar` (grouped or stacked), and `dual_axis`. The bottom of the notebook has a ready-to-paste example for each.

**Team style:** colors, fonts, and sizes come from `code/utils/graph_templates.py`. Change the style there and both this notebook and the older per-graph notebooks pick it up.

# Make a graph (custom notebook)
For a graph that needs custom Plotly code, copy `code/example.ipynb`, rename it, and follow its steps. Save each graph notebook in the `code` folder. Non-FRED data files go in `code/data`, and finished graphs are saved to `figures`.

# Troubleshooting
- **"Strict Open XML"**: the Excel file is saved in a format Python can't read. Open it in Excel, File > Save As, and choose **Excel Workbook (.xlsx)**.
- **`CERTIFICATE_VERIFY_FAILED`** when loading FRED data (common on Macs with python.org Python): re-run `pip install -r requirements.txt`. The graph tool fixes this automatically; for older notebooks, run the "Install Certificates.command" file in your Python folder in Applications.
- **"Saving PNGs needs Google Chrome"**: install Chrome, or run `plotly_get_chrome` in a terminal with the `.venv` activated.
- **"No module named ..."**: the notebook is using the wrong kernel. Select `.venv` at the top right.

# Code layout
```
make_graph.ipynb          quick graph maker (settings cell → PNG)
code/graph_tool/          the code behind it
    data_sources.py         loads FRED / Excel / CSV into one standard table
    charts.py               builds each chart type, saves PNGs
code/utils/               team Plotly template (graph_templates.py) and helpers
code/*.ipynb              one notebook per graph (older, custom graphs)
DATA2026/                 data files for make_graph.ipynb
code/data/                data files used by the older per-graph notebooks
figures/                  saved graphs (.html from notebooks, png/ from make_graph)
```

FRED API docs are here: https://fred.stlouisfed.org/docs/api/fred/

fredapi.py docs are here: https://pypi.org/project/fredapi/
