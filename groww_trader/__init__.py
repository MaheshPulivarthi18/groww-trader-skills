"""groww_trader: shared library behind the Groww trader skills.

Standard-library only. The live data source needs the official `growwapi`
package; everything else (scanning, planning, sizing, risk, backtesting)
runs offline on cached CSV candles.

Not financial advice. See README.md.
"""

__version__ = "0.5.0"
