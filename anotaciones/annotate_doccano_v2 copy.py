import sys
import json
import re
from pathlib import Path
import os
import unicodedata

#  fuzzy matcher opcional
try:
    from rapidfuzz import fuzz
    HAS_FUZZ = True
except:
    HAS_FUZZ = False

def fuzzy_similarity(a, b):
    """Fallback si rapidfuzz no existe."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


# CARGAR DICCIONARIO

def load_categories():
    dictionary_path = Path(__file__).parent / "dictionary.json"
    if not dictionary_path.exists():
        print("ERROR: No se encontró dictionary.json")
        sys.exit(1)

    with open(dictionary_path, "r", encoding="utf-8") as f:
        print("dictionary.json cargado correctamente")
        return json.load(f)

CATEGORIES = load_categories()

# NORMALIZACIÓN + LEMMATIZACIÓN

def normalize_text_for_matching(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()

def lightweight_lemma(word):
    """
    Lematización ultraligera para capturar variaciones.
    Agrega sufijos científicos típicos.
    """
    w = word.lower()
    suf_list = ["ing","ed","es","s","ion","ation","ment","ability","ization"]
    for suf in suf_list:
        if w.endswith(suf) and len(w) > len(suf)+2:
            return w[:-len(suf)]
    return w


# LIMPIEZA BASE

def clean_text(text):
    text = text.replace('\ufeff','').replace('\u200b','').replace('\xa0',' ')
    text = unicodedata.normalize('NFKC', text)
    text = text.replace('“','"').replace('”','"')
    text = text.replace('—','-')
    text = re.sub(r'\s*-\s*','-', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# PATRONES FLEXIBLES
# PALABRAS GENÉRICAS A EXCLUIR SUFJOS
EXCLUDE_SUFFIX_TERMS = {"note", "text", "data", "info", "section"}  # ajusta según necesites

# PATRONES FLEXIBLES MEJORADOS
def build_flexible_pattern(term):
    """
    Regex que permite letras, números y guiones dentro de la palabra.
    Mantiene lematización ligera para sufijos, salvo términos genéricos.
    """
    base = re.escape(term)
    lemma = re.escape(lightweight_lemma(term))
    
    # si el término es genérico, no permitimos sufijos
    if term.lower() in EXCLUDE_SUFFIX_TERMS:
        pattern = rf"(?<!\w)({base}|{lemma})(?!\w)"
    else:
        pattern = rf"(?<!\w)({base}|{lemma})(?:s|es|ing|ed|ion|ation|ment|ability|ization)?(?!\w)"
    
    return re.compile(pattern, flags=re.IGNORECASE)
# PRECOMPILE DE LOS PATRONES
PRECOMPILED = {}
for category, terms in CATEGORIES.items():
    terms_sorted = sorted(terms, key=lambda x: len(x), reverse=True)
    term_patterns = []
    for term in terms_sorted:
        pattern = build_flexible_pattern(term)
        term_patterns.append((term, pattern))
    PRECOMPILED[category] = term_patterns


# ANOTADOR MEJORADO
# PATRONES FLEXIBLES (ajustado)
def build_flexible_pattern(term):
    """
    Regex que permite letras, números y guiones dentro de la palabra.
    Mantiene lematización ligera para sufijos.
    Solo palabras con >=3 caracteres.
    """
    if len(term) < 3:
        return None  # ignorar términos demasiado cortos
    base = re.escape(term)
    lemma = re.escape(lightweight_lemma(term))
    pattern = rf"(?<!\w)({base}|{lemma})(?:s|es|ing|ed|ion|ation|ment|ability|ization)?(?!\w)"
    return re.compile(pattern, flags=re.IGNORECASE)

# ANOTADOR MEJORADO (ajustado)
def annotate_text(text):
    annotations = []
    used_spans = set()  # evita duplicados y superposiciones

    # Palabras únicas para fuzzy
    words = re.findall(r"\b[\w\-]{3,}\b", text)  # solo >=3 letras
    words_unique = list(dict.fromkeys(words))

    for category, term_list in PRECOMPILED.items():
        for original_term, pattern in term_list:
            if pattern is None:
                continue  # ignorar términos muy cortos

            # 1) Match exacto
            matched_here = False
            for match in pattern.finditer(text):
                span_range = (match.start(), match.end())
                if any(s <= span_range[0] < e or s < span_range[1] <= e for s, e in used_spans):
                    continue
                if lightweight_lemma(match.group(0)) == lightweight_lemma(original_term):
                    annotations.append([match.start(), match.end(), category])
                    used_spans.add(span_range)
                    matched_here = True

            # 2) Fuzzy matching solo si no hubo match exacto
            if not matched_here:
                target = normalize_text_for_matching(original_term)
                lemma_target = lightweight_lemma(target)

                for w in words_unique:
                    wn = normalize_text_for_matching(w)
                    if len(wn) < 3:  # descarta palabras muy cortas
                        continue
                    if lightweight_lemma(wn) == lemma_target:
                        continue
                    sim = fuzz.ratio(wn, target) if HAS_FUZZ else fuzzy_similarity(wn, target)
                    if sim >= 88:
                        idx = text.lower().find(w.lower())
                        if idx != -1:
                            span_range = (idx, idx+len(w))
                            if any(s <= span_range[0] < e or s < span_range[1] <= e for s, e in used_spans):
                                continue
                            annotations.append([idx, idx+len(w), category])
                            used_spans.add(span_range)
                        break  # un match fuzzy por término
    return annotations

# PROCESAMIENTO DE ARCHIVOS 

def process_single_file(possible_root):
    art_num = input("Número de artículo (ej: 17): ").strip()
    chunk_num = input("Número de chunk (ej: 6): ").strip()

    input_file = possible_root/"articulos_limpios"/f"art{art_num}"/f"art{art_num}_chunk_{chunk_num}.txt"
    if not input_file.exists():
        print(f"No se encontró el archivo: {input_file}")
        sys.exit(1)

    with open(input_file,"r",encoding="utf-8") as f:
        text = f.read()

    text_clean = clean_text(text)
    annotations = annotate_text(text_clean)

    output_folder = Path(__file__).parent / f"art{art_num}"
    os.makedirs(output_folder, exist_ok=True)

    output_file = output_folder / f"art{art_num}_chunk_{chunk_num}.jsonl"

    json_line = {
        "id": int(chunk_num),
        "text": text_clean,
        "label": annotations,
        "Comments": []
    }

    with open(output_file,"w",encoding="utf-8") as out:
        out.write(json.dumps(json_line, ensure_ascii=False, separators=(',',':'))+"\n")

    print(f"\nArchivo anotado generado: {output_file}")
    print(f"Total de anotaciones detectadas: {len(annotations)}")


# Procesamiento de carpetas y todos los chunks 

def process_folder(possible_root):
    art_num = input("Número de artículo (ej: 17): ").strip()
    input_dir = possible_root/"articulos_limpios"/f"art{art_num}"
    if not input_dir.exists():
        print(f"No se encontró el directorio: {input_dir}")
        sys.exit(1)

    all_chunks = sorted([f for f in input_dir.glob(f"art{art_num}_chunk_*.txt")])
    if not all_chunks:
        print("No se encontraron chunks.")
        sys.exit(1)

    output_folder = Path(__file__).parent/f"art{art_num}"
    os.makedirs(output_folder, exist_ok=True)

    total_annotations = 0

    for file_path in all_chunks:
        chunk_str = file_path.stem.split("_")[-1]
        with open(file_path,"r",encoding="utf-8") as f:
            text = f.read()

        text_clean = clean_text(text)
        annotations = annotate_text(text_clean)
        total_annotations += len(annotations)

        output_file = output_folder/f"art{art_num}_chunk_{chunk_str}.jsonl"
        json_line = {"id": int(chunk_str), "text": text_clean, "label": annotations, "Comments":[]}
        with open(output_file,"w",encoding="utf-8") as out:
            out.write(json.dumps(json_line, ensure_ascii=False, separators=(',',':'))+"\n")
        print(f"✓ Procesado: {output_file} ({len(annotations)} anotaciones)")

    print("\nProcesamiento completado.")
    print(f"Total de chunks: {len(all_chunks)}")
    print(f"Total anotaciones: {total_annotations}")

def process_all_articles(possible_root):
    base_dir = possible_root/"articulos_limpios"
    if not base_dir.exists():
        print("No existe la carpeta articulos_limpios.")
        sys.exit(1)

    art_dirs = sorted([d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("art")])
    if not art_dirs:
        print("No hay carpetas artXX.")
        sys.exit(1)

    print("\nProcesando TODOS los artículos:", [d.name for d in art_dirs])

    total_annotations_global = 0
    total_chunks_global = 0

    for art_dir in art_dirs:
        art_num = art_dir.name.replace("art","")
        output_folder = Path(__file__).parent / f"art{art_num}"
        os.makedirs(output_folder, exist_ok=True)

        chunks = sorted(art_dir.glob(f"art{art_num}_chunk_*.txt"))
        for file_path in chunks:
            chunk_str = file_path.stem.split("_")[-1]
            with open(file_path,"r",encoding="utf-8") as f:
                text = f.read()
            text_clean = clean_text(text)
            annotations = annotate_text(text_clean)

            total_annotations_global += len(annotations)
            total_chunks_global += 1

            output_file = output_folder/f"art{art_num}_chunk_{chunk_str}.jsonl"
            json_line = {"id": int(chunk_str), "text": text_clean, "label": annotations, "Comments":[]}
            with open(output_file,"w",encoding="utf-8") as out:
                out.write(json.dumps(json_line, ensure_ascii=False, separators=(',',':'))+"\n")
            print(f"✓ {output_file} ({len(annotations)} anotaciones)")

    print("\nRESUMEN COMPLETO")
    print(f"Artículos: {len(art_dirs)}")
    print(f"Chunks: {total_chunks_global}")
    print(f"Anotaciones: {total_annotations_global}")

# MAIN

def main():
    print("\nSeleccione una opción:")
    print("1. Procesar un solo archivo .txt")
    print("2. Procesar todos los chunks de un artículo")
    print("3. Procesar TODOS los artículos y TODOS los chunks")
    choice = input("Opción (1/2/3): ").strip()

    current_dir = Path(__file__).resolve().parent
    possible_root = None

    for parent in [current_dir, *current_dir.parents]:
        test_path = parent/"BioBERT-CMC-"
        if test_path.exists():
            possible_root = test_path
            break

    if not possible_root:
        print("No se encontró la carpeta raíz BioBERT-CMC-.")
        sys.exit(1)

    if choice=="1":
        process_single_file(possible_root)
    elif choice=="2":
        process_folder(possible_root)
    elif choice=="3":
        process_all_articles(possible_root)
    else:
        print("Opción inválida.")
        sys.exit(1)

if __name__=="__main__":
    main()
