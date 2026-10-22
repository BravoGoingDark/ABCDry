import zipfile, re, datetime, os
import xml.etree.ElementTree as ET

SRC = r"C:/Users/Taha/Desktop/bzrt1.xlsx"
OUTDIR = r"C:/Users/Taha/Desktop"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
GT = chr(62); LT = chr(60)

def T(s):
    return s.replace("#GT#", GT).replace("#LT#", LT)

z = zipfile.ZipFile(SRC)
ss = ["".join(t.text or "" for t in si.iter(M+"t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]

def load_sheet(n):
    rows = []
    for r in ET.fromstring(z.read("xl/worksheets/%s.xml" % n)).iter(M+"row"):
        d = {}
        for c in r.iter(M+"c"):
            ref = c.get("r"); col = re.match(r"([A-Z]+)", ref).group(1)
            v = c.find(M+"v")
            if c.get("t") == "s":
                val = ss[int(v.text)] if v is not None else None
            elif c.get("t") == "inlineStr":
                t = c.find(M+"is/"+M+"t"); val = t.text if t is not None else None
            else:
                val = v.text if v is not None else None
            d[col] = val
        rows.append(d)
    return rows

def colnum(letters):
    n = 0
    for L in letters: n = n*26 + ord(L)-64
    return n-1

def esc(s):
    return s.replace("&","&amp;").replace(T("#LT#"),"&lt;").replace(T("#GT#"),"&gt;")

def cell_xml(ref, val):
    if val is None or val == "": return T('#LT#c r="#R"/#GT#').replace("#R", ref)
    if isinstance(val, str):
        return T('#LT#c r="#R#" t="inlineStr"#GT##LT#is#GT##LT#t xml:space="preserve"#GT##V##LT#/t#GT##LT#/is#GT##LT#/c#GT#').replace("#R#", ref).replace("#V#", esc(val))
    return T('#LT#c r="#R"#GT##LT#v#GT##V##LT#/v#GT##LT#/c#GT#').replace("#R", ref).replace("#V#", str(val))

def rowxml(rnum, vals):
    cells = "".join(cell_xml(chr(65+i) + str(rnum), v) for i, v in enumerate(vals))
    return T('#LT#row r="#N"#GT##C##LT#/row#GT#').replace("#N", str(rnum)).replace("#C#", cells)

def write_xlsx(path, headers, rows):
    ct = T('#LT#?xml version="1.0" encoding="UTF-8" standalone="yes"?#GT##LT#Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"#GT##LT#Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/#GT##LT#Default Extension="xml" ContentType="application/xml"/#GT##LT#Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/#GT##LT#Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/#GT##LT#/Types#GT#')
    rels = T('#LT#?xml version="1.0" encoding="UTF-8" standalone="yes"?#GT##LT#Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"#GT##LT#Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/#GT##LT#/Relationships#GT#')
    wb = T('#LT#?xml version="1.0" encoding="UTF-8" standalone="yes"?#GT##LT#workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"#GT##LT#sheets#GT##LT#sheet name="Data" sheetId="1" r:id="rId1"/#GT##LT#/sheets#GT##LT#/workbook#GT#')
    wbr = T('#LT#?xml version="1.0" encoding="UTF-8" standalone="yes"?#GT##LT#Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"#GT##LT#Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/#GT##LT#/Relationships#GT#')
    parts = [T('#LT#?xml version="1.0" encoding="UTF-8" standalone="yes"?#GT##LT#worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"#GT##LT#sheetData#GT#')]
    parts.append(rowxml(1, headers))
    for i, row in enumerate(rows, start=2):
        parts.append(rowxml(i, row))
    parts.append(T('#LT#/sheetData#GT##LT#/worksheet#GT#'))
    zf = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    zf.writestr("[Content_Types].xml", ct)
    zf.writestr("_rels/.rels", rels)
    zf.writestr("xl/workbook.xml", wb)
    zf.writestr("xl/_rels/workbook.xml.rels", wbr)
    zf.writestr("xl/worksheets/sheet1.xml", "".join(parts))
    zf.close()

def xldate(v):
    return (datetime.date(1899,12,30) + datetime.timedelta(days=float(v))).isoformat()

REGION = "Bizerte"
STAGE_MAP = {"Initial":"Germination", "Developpement":"Vegetative", "D?veloppement":"Vegetative",
             "Mi-saison":"Flowering", "Fin de saison":"Maturity", "Maturity":"Maturity"}

rows = load_sheet("sheet3")
hdr = {}
for col, val in rows[0].items():
    if val is not None:
        hdr[col] = str(val).strip()
def g(row, name):
    for col, h in hdr.items():
        if h == name: return row.get(col)
    return None
climate_out = []
for row in rows[1:]:
    rawdate = g(row, "measurement_date")
    if not rawdate: continue
    d = xldate(rawdate)
    climate_out.append([
        REGION, d[:4], d,
        g(row, "latitude"), g(row, "longitude"), g(row, "subregion"),
        g(row, "rainfall_mm"), g(row, "rainfall_source"), g(row, "seasonal_rainfall_variability"),
        g(row, "temperature_max_c"), g(row, "temperature_min_c"), g(row, "temperature_mean_c"),
        g(row, "relative_humidity_percent"), g(row, "wind_speed_ms"), g(row, "solar_radiation_mjm2day"),
        g(row, "evapotranspiration_et0_mmday"), g(row, "evapotranspiration_etc_mmday"),
    ])
CLIMATE_COLS = ["region","year","measurement_date","latitude","longitude","subregion","rainfall_mm","rainfall_source","seasonal_rainfall_variability","temperature_max_c","temperature_min_c","temperature_mean_c","relative_humidity_percent","wind_speed_ms","solar_radiation_mjm2day","evapotranspiration_et0_mmday","evapotranspiration_etc_mmday"]
out1 = OUTDIR + r"\bzrt1_climate_template.xlsx"
write_xlsx(out1, CLIMATE_COLS, climate_out)
print("climate rows written:", len(climate_out))

rows = load_sheet("sheet1")
hdr = {}
for col, val in rows[0].items():
    if val is not None:
        hdr[col] = str(val).strip()
agri_out = []
for row in rows[1:]:
    rawdate = g(row, "Date")
    if not rawdate: continue
    d = xldate(rawdate)
    yr = str(int(float(g(row, "Ann?e")))) if g(row, "Ann?e") else d[:4]
    stage = STAGE_MAP.get((g(row, "Stade") or "").strip(), "Vegetative")
    agri_out.append([
        REGION, yr, d, (g(row, "Culture") or "").strip(),
        g(row, "latitude"), g(row, "longitude"), g(row, "subregion"),
        stage,
        g(row, "Kc"), g(row, "ETc (mm/jour)"),
        None, None, None, None, None, None,
    ])
AGRI_COLS = ["region","year","measurement_date","crop","latitude","longitude","subregion","growth_stage","crop_coefficient_kc","crop_water_requirement_mmday","yield_reduction_factor","irrigation_method","irrigation_efficiency_percent","water_applied_mm","leaf_temperature_c","stomatal_conductance"]
out2 = OUTDIR + r"\bzrt1_agricultural_template.xlsx"
write_xlsx(out2, AGRI_COLS, agri_out)
print("agricultural rows written:", len(agri_out))

for path, cols in [(out1, CLIMATE_COLS), (out2, AGRI_COLS)]:
    zz = zipfile.ZipFile(path)
    rr = list(ET.fromstring(zz.read("xl/worksheets/sheet1.xml")).iter(M+"row"))
    got = []
    for c in rr[0].iter(M+"c"):
        t = c.find(M+"is/"+M+"t")
        got.append(t.text if t is not None else (c.find(M+"v").text if c.find(M+"v") is not None else None))
    assert got == cols, (path, got)
    sample = []
    for c in rr[1].iter(M+"c"):
        t = c.find(M+"is/"+M+"t")
        sample.append(t.text if t is not None else (c.find(M+"v").text if c.find(M+"v") is not None else None))
    print("VERIFIED", os.path.basename(path), "- rows:", len(rr)-1, "- headers match template")
    print("  sample:", sample)
