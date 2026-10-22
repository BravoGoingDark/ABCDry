import zipfile, re, datetime, os
import xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
GT = chr(62); LT = chr(60)

def T(s):
    return s.replace("#GT#", GT).replace("#LT#", LT)

def load_ss(z):
    if "xl/sharedStrings.xml" in z.namelist():
        return ["".join(t.text or "" for t in si.iter(M+"t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    return []

def load_sheet(z, ss, n):
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

def esc(s):
    return s.replace("&", "&amp;").replace(T("#LT#"), "&lt;").replace(T("#GT#"), "&gt;")

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

STADE = {"Initial":"Germination", "Developpement":"Vegetative", "D?veloppement":"Vegetative",
         "Mi-saison":"Flowering", "Fin de saison":"Maturity", "Maturity":"Maturity"}

CLIMATE_COLS = ["year","measurement_date","latitude","longitude","rainfall_mm","temperature_max_c","temperature_min_c","temperature_mean_c","relative_humidity_percent","wind_speed_ms","solar_radiation_mjm2day","evapotranspiration_et0_mmday"]
AGRI_COLS = ["year","measurement_date","crop","latitude","longitude","growth_stage","crop_coefficient_kc","crop_water_requirement_mmday"]

JOBS = [
    dict(src=r"C:/Users/Taha/Downloads/climate_data_station1ver.xlsx",
         tag="station1", lat="37.01", lon="9.731",
         climate_sheet="sheet1", etc_sheet="sheet3"),
    dict(src=r"C:/Users/Taha/Downloads/climate_data_sation2ver.xlsx",
         tag="station2", lat="37.117", lon="9.318",
         climate_sheet="sheet1", etc_sheet="sheet2"),
    dict(src=r"C:/Users/Taha/Desktop/bzrt1.xlsx",
         tag="bizerte", lat="37.01", lon="9.731",
         climate_sheet="sheet3", etc_sheet="sheet1"),
]

for job in JOBS:
    z = zipfile.ZipFile(job["src"])
    ss = load_ss(z)
    tag = job["tag"]; lat = job["lat"]; lon = job["lon"]

    rows = load_sheet(z, ss, job["climate_sheet"])
    hdr = {}
    for col, val in rows[0].items():
        if val is not None: hdr[col] = str(val).strip()
    def g(row, name):
        for col, h in hdr.items():
            if h == name: return row.get(col)
        return None
    out = []
    def gc(row, *names):
        for col, h in hdr.items():
            hs = "".join(ch for ch in h if ord(ch) < 128).strip().lower()
            for nm in names:
                if hs == nm: return row.get(col)
        return None
    for row in rows[1:]:
        d = g(row, "Date") or g(row, "measurement_date")
        if not d: continue
        iso = xldate(d)
        out.append([
            g(row, "year"), iso, lat, lon,
            gc(row, "precipitation_mm", "rainfall_mm"),
            gc(row, "tmax_c", "temperature_max_c"), gc(row, "tmin_c", "temperature_min_c"), gc(row, "tmean_c", "temperature_mean_c"),
            gc(row, "relative_humidity%", "relative_humidity% 2m", "relative_humidity_percent"),
            gc(row, "wind_speed_2m m/s", "wind_speed_ms"),
            gc(row, "solar_radiation_mj_m2_day", "solar_radiation_mjm2day"),
            gc(row, "et0 (mm/jour)", "eto (mm/jour)", "evapotranspiration_et0_mmday"),
        ])
    path = r"C:/Users/Taha/Desktop/%s_climate_template.xlsx" % tag
    write_xlsx(path, CLIMATE_COLS, out)
    print("wrote", os.path.basename(path), len(out), "rows")

    rows = load_sheet(z, ss, job["etc_sheet"])
    hdr = {}
    for col, val in rows[0].items():
        if val is not None: hdr[col] = str(val).strip()
    out = []
    for row in rows[1:]:
        d = g(row, "Date") or g(row, "measurement_date")
        if not d: continue
        iso = xldate(d)
        yr = str(int(float(g(row, "Ann?e")))) if g(row, "Ann?e") else iso[:4]
        out.append([
            yr, iso, (g(row, "Culture") or "").strip(), lat, lon,
            STADE.get((g(row, "Stade") or "").strip(), "Vegetative"),
            g(row, "Kc"), g(row, "ETc (mm/jour)"),
        ])
    path = r"C:/Users/Taha/Desktop/%s_agricultural_template.xlsx" % tag
    write_xlsx(path, AGRI_COLS, out)
    print("wrote", os.path.basename(path), len(out), "rows")

for f in ["station1_climate_template.xlsx","station2_climate_template.xlsx","bizerte_climate_template.xlsx","station1_agricultural_template.xlsx","station2_agricultural_template.xlsx","bizerte_agricultural_template.xlsx"]:
    p = r"C:/Users/Taha/Desktop/" + f
    zz = zipfile.ZipFile(p)
    rr = list(ET.fromstring(zz.read("xl/worksheets/sheet1.xml")).iter(M+"row"))
    got = []
    for c in rr[0].iter(M+"c"):
        t = c.find(M+"is/"+M+"t")
        got.append(t.text if t is not None else (c.find(M+"v").text if c.find(M+"v") is not None else None))
    sample = []
    for c in rr[1].iter(M+"c"):
        t = c.find(M+"is/"+M+"t")
        sample.append(t.text if t is not None else (c.find(M+"v").text if c.find(M+"v") is not None else None))
    print("VERIFIED", f, "rows:", len(rr)-1)
    print("   sample:", sample)
