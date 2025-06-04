import pandas as pd
import os
import glob
import re

# ---------------------------------------
# CONFIGURATION
# ---------------------------------------

# 1) Folder containing all raw March-2025 Excel files
RAW_FOLDER_PATH = r"C:/Users/Brian/Downloads/Warehouse_Mar2025"

# 2) Path for the consolidated output
OUTPUT_FILE = r"C:/Users/Brian/Downloads/Warehouse_Mar2025/Consolidated_Mar2025.xlsx"

# 3) Exactly the Top-10 companies we want to include
TOP_COMPANIES = [
    "Betime",
    "MG",
    "Ariston",
    "Wesco",
    "Simply Toy",
    "Smile Fam",
    "Gold Point",
    "Elite Legion",
    "Parker",
    "D-Gredient"
]

# Mapping from lowercase keyword → official company name
company_keywords = {
    'betime':       'Betime',
    'mg':           'MG',
    'ariston':      'Ariston',
    'wesco':        'Wesco',
    'simply toy':   'Simply Toy',
    'smile fam':    'Smile Fam',
    'gold point':   'Gold Point',
    'elite legion': 'Elite Legion',
    'parker':       'Parker',
    'd-gredient':   'D-Gredient'
}


# ---------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------

def detect_company(filename: str) -> str:
    """
    Look for a keyword in the filename and return the corresponding 'official' company name.
    """
    lower = filename.lower()
    for key, val in company_keywords.items():
        if key in lower:
            return val
    # If none of our keywords match, default to using the first word of the filename (capitalized)
    return os.path.splitext(os.path.basename(filename))[0].split()[0].title()


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns based on common keyword patterns—but drop any 'Volume' columns entirely:
      - OrderNo:     contains 'order no', 'lot no', 'reference no', 'references',
                     'receipt#', 'system gr/gi no', 'gino', 'issue#', 'gr/gi'
      - Quantity:    contains 'qty', 'quantity', 'units', 'total plt', 'pcs',
                     'ctn', 'plt', 'pallet', 'pallets', 'carton', 'cartons'
      - Date:        contains 'drop order date', 'shippedon', 'finalized date',
                     'delivery date', or simply 'date'
      - Type:        contains 'typem' or 'type'
    Any column containing 'm3' is ignored (we do not pull “Volume”).  
    After renaming, any exact‐duplicate column names get dropped (only the first occurrence is kept).
    """
    col_map = {}
    for col in df.columns:
        name = str(col)
        lower = name.lower().strip()
        if any(x in lower for x in [
            'order no', 'lot no', 'reference no', 'references',
            'receipt#', 'system gr/gi no', 'gino', 'issue#', 'gr/gi'
        ]):
            col_map[col] = 'OrderNo'
        elif any(x in lower for x in [
            'qty', 'quantity', 'units', 'total plt',
            'pcs', 'ctn', 'plt', 'pallet', 'pallets', 'carton', 'cartons'
        ]):
            col_map[col] = 'Quantity'
        elif any(x in lower for x in [
            'drop order date', 'shippedon', 'finalized date',
            'delivery date', 'date'
        ]):
            col_map[col] = 'Date'
        elif 'typem' in lower or 'type' in lower:
            col_map[col] = 'Type'
        else:
            # Everything else is left “as is”—we’ll drop Volume columns manually by not using them.
            col_map[col] = name

    df = df.rename(columns=col_map)
    # Drop any exact-duplicate column names (keeping only the first occurrence)
    df = df.loc[:, ~df.columns.duplicated()]
    return df


def extract_numeric_from_string(value: str) -> float:
    """
    Given a string such as '546 CTN' or '7.74144', extract the numeric portion.
    Returns a float, or NaN if no valid number is found.
    """
    if pd.isna(value):
        return float('nan')
    s = str(value)
    match = re.search(r'[\d,]*\.?\d+', s)
    if match:
        num_str = match.group(0).replace(',', '')
        try:
            return float(num_str)
        except ValueError:
            return float('nan')
    return float('nan')


# ---------------------------------------
# MAIN CONSOLIDATION + DASHBOARD CREATION
# ---------------------------------------

def consolidate_and_create_dashboard(folder_path: str, top_companies: list, output_path: str):
    """
    1) Read every .xlsx in folder_path whose filename matches one of the Top-10 companies.
    2) Standardize each sheet’s columns, tag Company & Type as needed.
    3) Concatenate everything into one DataFrame.
    4) Immediately force every Type to upper-case + strip whitespace.
    5) Filter strictly to dates in [2025-03-01 .. 2025-03-31].
    6) Parse 'Quantity' to numeric, drop any row where it’s null.
    7) Take the absolute value of Quantity (so Inbound and Outbound are both positive).
    8) For Elite Legion: keep only rows whose Type ∈ { 'INBOUND', 'OUTBOUND' }.
    9) For MG: only read “Summary 2025” (or MG Summary/Summary/DATA), map “GOODS RETURNED” → “INBOUND,” 
       and leave true “OUTBOUND” as-is.
    10) Write the final March-2025 table to sheet “Data.”
    11) On sheet “Dashboard,” insert four charts:
         • Pie chart: Inbound Quantity by Company.
         • Pie chart: Outbound Quantity by Company.
         • Line chart: daily Inbound vs Outbound (all companies combined).
         • Multi-line chart: daily Inbound/Outbound by Company.
    """
    all_rows = []

    # ----- A) Read & Standardize Each File -----
    for filepath in glob.glob(os.path.join(folder_path, '*.xlsx')):
        fname = os.path.basename(filepath)
        if fname.startswith('~$'):
            # Skip temporary lock files.
            continue

        company = detect_company(fname)
        if company not in top_companies:
            continue

        xls = pd.ExcelFile(filepath)
        sheets = xls.sheet_names

        # ----- 1) Betime: “INBOUND REPORT” & “Outbound report” -----
        if company == 'Betime':
            for sheet_name, t in [('INBOUND REPORT', 'INBOUND'),
                                  ('Outbound report', 'OUTBOUND')]:
                if sheet_name in sheets:
                    df = pd.read_excel(filepath, sheet_name=sheet_name)
                    df = standardize_columns(df)
                    df['Type'] = t
                    df['Company'] = company
                    all_rows.append(df)

        # ----- 2) Wesco: “ReceivingInfo” (INBOUND) & “IssuingInfo” (OUTBOUND) -----
        elif company == 'Wesco':
            for sheet_name, t in [('ReceivingInfo', 'INBOUND'),
                                  ('IssuingInfo', 'OUTBOUND')]:
                if sheet_name in sheets:
                    df = pd.read_excel(filepath, sheet_name=sheet_name)
                    df = standardize_columns(df)
                    df['Type'] = t
                    df['Company'] = company
                    all_rows.append(df)

        # ----- 3) Elite Legion: only “INVENTORY” sheet; keep rows where Type ∈ {INBOUND, OUTBOUND} -----
        elif company == 'Elite Legion':
            if 'INVENTORY' in sheets:
                df = pd.read_excel(filepath, sheet_name='INVENTORY')
                df = standardize_columns(df)
                if 'Type' in df.columns:
                    df['Type'] = df['Type'].astype(str).str.upper().str.strip()
                    df = df[df['Type'].isin(['INBOUND', 'OUTBOUND'])]
                else:
                    # If there is no Type column, treat everything as INBOUND
                    df['Type'] = 'INBOUND'
                df['Company'] = company
                all_rows.append(df)
            else:
                print(f"⚠ Warning: 'INVENTORY' sheet not found in {fname}")

        # ----- 4) MG: only “Summary 2025” (or MG Summary/Summary/DATA); map “GOODS RETURNED” → “INBOUND” -----
        elif company == 'MG':
            # Look for exactly “Summary 2025” first (then fallback to MG Summary, Summary, or DATA).
            target = None
            for candidate in ['Summary 2025', 'MG Summary', 'Summary', 'DATA']:
                if candidate in sheets:
                    target = candidate
                    break
            if target:
                df = pd.read_excel(filepath, sheet_name=target)
                df = standardize_columns(df)

                # The “Quantity” column now holds strings like “14 CTN” or “5 CTN,” etc.
                if 'Quantity' in df.columns:
                    df['Quantity'] = df['Quantity'].apply(extract_numeric_from_string)

                # Normalize Type (if present) and convert “GOODS RETURNED” → “INBOUND”
                if 'Type' in df.columns:
                    df['Type'] = df['Type'].astype(str).str.upper().str.strip()
                    df.loc[df['Type'] == 'GOODS RETURNED', 'Type'] = 'INBOUND'
                    # Any actual “OUTBOUND” remains “OUTBOUND”.
                else:
                    df['Type'] = None

                df['Company'] = company
                all_rows.append(df)
            else:
                print(f"⚠ Warning: No MG “Summary 2025” (or MG Summary/Summary/DATA) sheet found in {fname}")

        # ----- 5) All other companies: prefer “INVENTORY,” else “Summary 2025” / “Summary” / “DATA” -----
        else:
            target = None
            for candidate in ['INVENTORY', 'Summary 2025', 'Summary', 'DATA']:
                if candidate in sheets:
                    target = candidate
                    break
            if target:
                df = pd.read_excel(filepath, sheet_name=target)
                df = standardize_columns(df)
                if 'Type' not in df.columns:
                    df['Type'] = None
                df['Company'] = company
                all_rows.append(df)
            else:
                print(f"⚠ Warning: No relevant sheet found in {fname}")

    # If no valid data ended up in all_rows, we can stop here.
    if not all_rows:
        print("No data found for the Top-10 companies.")
        return

    # ----- B) Concatenate Everything Into One DataFrame -----
    combined = pd.concat(all_rows, ignore_index=True, sort=False)

    # ----- C) Immediately Normalize Every Type to uppercase + strip whitespace -----
    combined['Type'] = combined['Type'].fillna('').astype(str).str.upper().str.strip()

    # ----- D) Keep only the five columns we need; drop everything else (including any Volume columns). -----
    keep_cols = ['Company', 'Date', 'OrderNo', 'Quantity', 'Type']
    for c in keep_cols:
        if c not in combined.columns:
            combined[c] = None
    combined = combined[keep_cols]

    # ----- E) Restrict strictly to March 2025 (2025-03-01 through 2025-03-31) -----
    combined['Date'] = pd.to_datetime(combined['Date'], errors='coerce').dt.date
    combined = combined[
        (combined['Date'] >= pd.to_datetime("2025-03-01").date()) &
        (combined['Date'] <= pd.to_datetime("2025-03-31").date())
    ]

    # ----- F) Convert Quantity → numeric, drop rows where it’s null -----
    combined['Quantity'] = pd.to_numeric(combined['Quantity'], errors='coerce')
    combined = combined[combined['Quantity'].notna()].copy()

    # ----- G) Force ALL quantities to be positive (abs) so “Inbound” never ends up negative -----
    combined['Quantity'] = combined['Quantity'].abs()

    # ----- H) At this point, Type ∈ { '', 'INBOUND', 'OUTBOUND', … } -----
    # We will only chart the rows whose Type is exactly “INBOUND” or “OUTBOUND.”  

    # ----- I) Write to Excel with two sheets: “Data” + “Dashboard” -----
    with pd.ExcelWriter(output_path, engine='xlsxwriter', datetime_format='yyyy-mm-dd') as writer:
        # 1) Write the cleaned March-2025 data to sheet “Data”
        combined.to_excel(writer, sheet_name='Data', index=False)

        workbook  = writer.book
        dashboard = workbook.add_worksheet('Dashboard')
        writer.sheets['Dashboard'] = dashboard

        # ===== 1) PIE CHART: Inbound Quantity by Company =====
        inbound_by_company = (
            combined[combined['Type'] == 'INBOUND']
            .groupby('Company')['Quantity']
            .sum()
            .reset_index()
            .sort_values('Quantity', ascending=False)
        )
        inbound_by_company.to_excel(
            writer,
            sheet_name='Dashboard',
            startrow=0,
            startcol=0,
            index=False,
            header=['Company','InboundQuantity']
        )
        n_in = len(inbound_by_company)

        pie_in = workbook.add_chart({'type': 'pie'})
        pie_in.add_series({
            'name'      : 'Inbound Quantity by Company',
            'categories': ['Dashboard', 1, 0, n_in, 0],
            'values'    : ['Dashboard', 1, 1, n_in, 1],
            'data_labels': {'percentage': True},
        })
        pie_in.set_title({'name': 'Inbound Quantity by Company'})
        dashboard.insert_chart('D1', pie_in, {'x_scale': 1.0, 'y_scale': 1.0})

        # ===== 2) PIE CHART: Outbound Quantity by Company =====
        outbound_by_company = (
            combined[combined['Type'] == 'OUTBOUND']
            .groupby('Company')['Quantity']
            .sum()
            .reset_index()
            .sort_values('Quantity', ascending=False)
        )
        outbound_by_company.to_excel(
            writer,
            sheet_name='Dashboard',
            startrow=0,
            startcol=5,   # place this pie starting at column F (zero-based)
            index=False,
            header=['Company','OutboundQuantity']
        )
        n_out = len(outbound_by_company)

        pie_out = workbook.add_chart({'type': 'pie'})
        pie_out.add_series({
            'name'      : 'Outbound Quantity by Company',
            'categories': ['Dashboard', 1, 5, n_out, 5],
            'values'    : ['Dashboard', 1, 6, n_out, 6],
            'data_labels': {'percentage': True},
        })
        pie_out.set_title({'name': 'Outbound Quantity by Company'})
        dashboard.insert_chart('J1', pie_out, {'x_scale': 1.0, 'y_scale': 1.0})

        # ===== 3) LINE CHART: Daily Inbound vs Outbound (All Companies Combined) =====
        daily = (
            combined
            .groupby(['Date','Type'])['Quantity']
            .sum()
            .reset_index()
        )
        daily_pivot = daily.pivot(index='Date', columns='Type', values='Quantity').fillna(0)

        all_days = pd.date_range('2025-03-01', '2025-03-31', freq='D').date
        daily_pivot = daily_pivot.reindex(all_days, fill_value=0).reset_index().rename(columns={'index':'Date'})

        start_row = max(n_in, n_out) + 4
        daily_pivot.to_excel(
            writer,
            sheet_name='Dashboard',
            startrow=start_row,
            startcol=0,
            index=False
        )
        max_row = start_row + len(daily_pivot)

        line_all = workbook.add_chart({'type': 'line'})
        if 'INBOUND' in daily_pivot.columns:
            line_all.add_series({
                'name'      : 'Inbound (All)',
                'categories': ['Dashboard', start_row+1, 0, max_row, 0],
                'values'    : ['Dashboard', start_row+1, daily_pivot.columns.get_loc('INBOUND'),
                                max_row, daily_pivot.columns.get_loc('INBOUND')],
                'marker': {'type': 'circle', 'size': 4},
            })
        if 'OUTBOUND' in daily_pivot.columns:
            line_all.add_series({
                'name'      : 'Outbound (All)',
                'categories': ['Dashboard', start_row+1, 0, max_row, 0],
                'values'    : ['Dashboard', start_row+1, daily_pivot.columns.get_loc('OUTBOUND'),
                                max_row, daily_pivot.columns.get_loc('OUTBOUND')],
                'marker': {'type': 'diamond', 'size': 4},
            })
        line_all.set_title({'name': 'Daily In/Out Quantity (All Companies)'})
        line_all.set_x_axis({
            'name': 'Date', 'date_axis': True, 'num_format': 'yyyy-mm-dd', 'label_position':'low'
        })
        line_all.set_y_axis({'name': 'Quantity'})
        line_all.set_legend({'position': 'bottom'})
        dashboard.insert_chart('D20', line_all, {'x_scale': 1.3, 'y_scale': 1.1})

        # ===== 4) MULTI-LINE CHART: Daily Inbound/Outbound by Company =====
        daily_by_company = (
            combined
            .groupby(['Date','Company','Type'])['Quantity']
            .sum()
            .reset_index()
        )
        pivot_multi = daily_by_company.pivot(
            index='Date',
            columns=['Company','Type'],
            values='Quantity'
        ).fillna(0)

        # Make sure every date in March 2025 is present:
        pivot_multi = pivot_multi.reindex(all_days, fill_value=0).reset_index().rename(columns={'index':'Date'})

        # Flatten the MultiIndex columns into single strings, e.g. “Betime - INBOUND”
        flat_columns = []
        for col in pivot_multi.columns:
            if isinstance(col, tuple):
                flat_columns.append(f"{col[0]} - {col[1]}")
            else:
                flat_columns.append(col)
        pivot_multi.columns = flat_columns

        pivot_start = max_row + 3
        pivot_multi.to_excel(
            writer,
            sheet_name='Dashboard',
            startrow=pivot_start,
            startcol=0,
            index=False
        )
        pivot_end = pivot_start + len(pivot_multi)
        num_cols = pivot_multi.shape[1]

        line_multi = workbook.add_chart({'type': 'line'})
        for col_idx in range(1, num_cols):
            series_name = pivot_multi.columns[col_idx]
            line_multi.add_series({
                'name'      : series_name,
                'categories': ['Dashboard', pivot_start+1, 0, pivot_end, 0],
                'values'    : ['Dashboard', pivot_start+1, col_idx, pivot_end, col_idx],
                'marker': {'type': 'circle', 'size': 3},
            })
        line_multi.set_title({'name': 'Daily In/Out Quantity by Company (Mar 2025)'})
        line_multi.set_x_axis({
            'name': 'Date', 'date_axis': True, 'num_format': 'yyyy-mm-dd', 'label_position':'low'
        })
        line_multi.set_y_axis({'name': 'Quantity'})
        line_multi.set_legend({'position': 'bottom', 'font': {'size': 8}})
        dashboard.insert_chart('D40', line_multi, {'x_scale': 1.5, 'y_scale': 1.1})

        # No explicit writer.save() needed—exiting the with-block automatically saves the file.

    print(f"Consolidation + Dashboard charts complete. Output: '{output_path}'")


if __name__ == '__main__':
    consolidate_and_create_dashboard(RAW_FOLDER_PATH, TOP_COMPANIES, OUTPUT_FILE)
