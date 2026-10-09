"""Génération des fichiers Excel (émargement, bilans d'absences)."""
import io

import pandas as pd
from openpyxl.styles import Font, PatternFill

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def excel_avec_entete(df: pd.DataFrame, feuille: str, entete: list):
    """Tableau Excel précédé de quelques lignes d'en-tête, colonnes ajustées."""
    sortie = io.BytesIO()
    with pd.ExcelWriter(sortie, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=feuille, startrow=len(entete) + 1)
        ws = writer.sheets[feuille]
        for i, ligne in enumerate(entete, start=1):
            ws.cell(row=i, column=1, value=ligne).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
        for cellule in ws[len(entete) + 2]:
            cellule.font = Font(bold=True, color="FFFFFF")
            cellule.fill = PatternFill("solid", fgColor="343A40")
        for col in ws.iter_cols(min_row=len(entete) + 2):
            largeur = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = max(12, largeur + 2)
    sortie.seek(0)
    return sortie
