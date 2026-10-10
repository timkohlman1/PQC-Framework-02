"""Exercise notebook logic with test selections, preserving researchers' saved cells."""
from pathlib import Path
import nbformat


def analysis_book():
    path=Path(__file__).resolve().parents[1]/'notebooks/analysis.ipynb'
    book=nbformat.read(path,as_version=4)
    for cell in book.cells:
        if cell.cell_type!='code':continue
        cell.outputs=[];cell.execution_count=None
        # The public notebook deliberately allows users to edit its settings.
        # Inject test inputs at the branch boundary in this in-memory copy only.
        if '\nif SPEC_FILE:' in cell.source:
            cell.source=cell.source.replace('\nif SPEC_FILE:',
                '\nSPEC_FILE = os.environ["PQC_ANALYSIS_SPEC"]\nif SPEC_FILE:',1)
        if '\nif SAVE and spec is not None:' in cell.source:
            cell.source=cell.source.replace('\nif SAVE and spec is not None:',
                '\nSAVE = os.environ.get("PQC_ANALYSIS_PUBLISH") == "1"\nOUTPUT = os.environ.get("PQC_ANALYSIS_OUTPUT")\nif SAVE and spec is not None:',1)
    return book
