import pikepdf
from pathlib import Path

RAW = Path('pdf_pipeline/raw')

pdfs = list(RAW.glob('*.pdf'))
if not pdfs:
    print('Aucun PDF dans pdf_pipeline/raw/')

for pdf_path in pdfs:
    print(f'\n{"="*50}')
    print(f'Fichier : {pdf_path.name}')

    with pikepdf.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f'\n--- Page {i+1} ---')

            if '/Contents' not in page:
                continue

            contents = page['/Contents']
            streams = [contents] if not isinstance(contents, pikepdf.Array) else list(contents)

            for stream in streams:
                try:
                    # read_bytes() décompresse le contenu
                    data = stream.read_bytes().decode('latin-1', errors='ignore')
                    
                    mots = ['yeninformatique', 'touteninformatique', 
                            'sujetexa', 'mongosukulu', '.com', 'www']
                    
                    for mot in mots:
                        if mot.lower() in data.lower():
                            idx = data.lower().find(mot.lower())
                            debut = max(0, idx - 400)
                            fin = min(len(data), idx + 400)
                            print(f'TROUVÉ : "{mot}"')
                            print(repr(data[debut:fin]))
                except Exception as e:
                    print(f'Erreur stream : {e}')
