"""
Debug : affiche le contenu brut du flux PDF pour comprendre
pourquoi le cleaner ne supprime pas les filigranes.
Usage : python debug_watermark.py fichier.pdf
"""
import sys, re
from pathlib import Path
import pikepdf

pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not pdf_path or not pdf_path.exists():
    print("Usage : python debug_watermark.py fichier.pdf")
    sys.exit(1)

KW = 'mongosukulu'

with pikepdf.open(str(pdf_path)) as pdf:
    for page_num, page in enumerate(pdf.pages):
        print(f"\n{'='*60}")
        print(f"PAGE {page_num + 1}")

        if '/Contents' not in page:
            print("  Pas de Contents")
            continue

        contents = page['/Contents']
        streams = list(contents) if isinstance(contents, pikepdf.Array) else [contents]

        for si, stream in enumerate(streams):
            try:
                data = stream.read_bytes()
                texte = data.decode('latin-1', errors='ignore')

                # Chercher le mot-clé
                pos = texte.lower().find(kw := KW.lower())
                if pos == -1:
                    print(f"  Stream {si} : mot-clé ABSENT ({len(texte)} chars)")
                    continue

                # Afficher le contexte autour du mot-clé
                debut = max(0, pos - 200)
                fin   = min(len(texte), pos + 200)
                contexte = texte[debut:fin]
                print(f"  Stream {si} : mot-clé TROUVÉ à pos {pos}")
                print(f"  Contexte :")
                print(f"  {repr(contexte)}")

                # Compter les BT/ET autour
                avant = texte[:pos]
                nb_bt = avant.upper().count('BT')
                nb_et = avant.upper().count('ET')
                print(f"  BT avant le mot-clé : {nb_bt} | ET avant : {nb_et}")

                # Chercher le BT le plus proche AVANT le mot-clé
                bt_pos = avant.rfind('\nBT')
                if bt_pos == -1:
                    bt_pos = avant.rfind(' BT')
                print(f"  BT précédent à pos : {bt_pos}")
                distance_bt = pos - bt_pos if bt_pos != -1 else -1
                print(f"  Distance BT→mot-clé : {distance_bt} chars")

            except Exception as e:
                print(f"  Stream {si} : ERREUR {e}")

        # Vérifier XObjects
        if '/Resources' in page:
            res = page['/Resources']
            if '/XObject' in res:
                xobjs = res['/XObject']
                print(f"\n  XObjects : {list(xobjs.keys())}")
                for key in xobjs:
                    xobj = xobjs[key]
                    subtype = str(xobj.get('/Subtype', ''))
                    print(f"    {key} → {subtype}")
                    if subtype == '/Form':
                        try:
                            d = xobj.read_bytes().decode('latin-1', errors='ignore')
                            if KW in d.lower():
                                print(f"    ⚠️  MOT-CLÉ TROUVÉ dans ce Form XObject !")
                        except Exception:
                            pass