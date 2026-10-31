# S&P 500 CEO Big Five Scoring

Rate CEO Big Five traits with ChatGPT and DeepSeek using the same  prompt.

Install Python 3.11+ with Tcl/Tk and pip, then unzip the repository. The [python.org macOS installer](https://www.python.org/download/mac/tcltk/) includes Tk. First launch installs dependencies into the project folder and requires internet access.

| System | Start the window |
| --- | --- |
| Windows | Double-click **Start Scoring.cmd**. |
| macOS / MacBook | Double-click **Start Scoring.command**. |

If macOS reports an execution-permission error, open Terminal in the project folder and run `chmod +x "Start Scoring.command"` once, then double-click it again ([Apple instructions](https://support.apple.com/en-il/guide/terminal/apdd100908f-06b3-4e63-8a87-32e71241bab4/mac)). You can also run `python3 scripts/launch.py` from that folder.

1. **Select data:** the default input is `data/sp500_ceos.csv`, containing all 500 study CEOs and their companies. You can also choose your own CSV with `ceo_id,name,company` columns. Common encodings and comma, semicolon or tab separators are supported; select **Advanced → CSV encoding** if automatic detection is ambiguous.
2. **Connect:** enter your OpenAI and/or DeepSeek key and model ID in **Connections**. API runs incur charges.
3. **Collect:** set **Valid scores per CEO / trait** (window default: 10), tick the models and traits, then click **Start / Resume**. For a full study collection, select both models, all five traits and 100 scores: 500,000 valid ratings. Text refusals, invalid scores and transient errors are retried. Invalid keys and non-retryable errors stop collection. **Stop** saves progress for resuming.
4. **Results:** click **Open results**. XLSX tables are in the selected folder as `model-trait-count.xlsx`. CSVs, logs and resume records are in `records/model-trait-count/`. Incomplete CSVs have a `.partial.csv` suffix; invalid scores are excluded.

**Archived study results:** `archived_ratings/ChatGPT.csv` and `archived_ratings/DeepSeek.csv` contain 500,000 History rating we have generated. 
