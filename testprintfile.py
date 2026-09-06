#Test ability to read file
import sys
import pandas as pd

try:
    import openpyxl
except ImportError:
    print("Missing dependency: openpyxl. Install it with: pip install openpyxl")
    sys.exit(1)


workbook = openpyxl.load_workbook("session1.xlsx")
wb1=pd.read_excel("session1.xlsx", sheet_name="Sheet1").head()
wb2=pd.read_excel("session1.xlsx", sheet_name="Sheet2").head()
txt_reader = open("InstructionForAI.txt", "r", encoding="utf-8")
text_from_pdf = txt_reader.read()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print(text_from_pdf)
print(wb1.to_markdown(index=False) )
print(wb2.to_markdown(index=False) )
