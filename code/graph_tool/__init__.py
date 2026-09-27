"""
graph_tool: make Fed Challenge graphs from FRED, Excel, or CSV data.

Every loader returns the same shape of table: a DataFrame with a DatetimeIndex
named "Date" and one numeric column per series (one column = one line/bar).
"""

from .data_sources import load_data, load_fred, load_file, preview
from .charts import make_chart, save_png, COLORS
