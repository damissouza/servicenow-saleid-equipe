"""Identificação estrita dos tipos aceitos pelo fluxo de resolução."""
# Permite executar diretamente os scripts nas pastas por função.
import sys as _sys
from pathlib import Path as _Path
_project_root = _Path(__file__).resolve().parent
_sys.path.insert(0, str(_project_root))

import re
import bulk_update as base


def table_for(number):
    if re.fullmatch(r'INC\d{7,}', number):
        return 'incident'
    if re.fullmatch(r'RITM\d{7,}', number):
        return 'sc_req_item'
    raise base.Stop(f'Número inválido: {number!r}. Use INC ou RITM seguido dos dígitos.')


def parse_numbers(text):
    numbers, duplicates = [], []
    for token in re.split(r'[\s,;]+', text.strip()):
        if not token:
            continue
        number = token.upper()
        table_for(number)
        if number in numbers:
            duplicates.append(number)
        else:
            numbers.append(number)
    if not numbers:
        raise base.Stop('Lista vazia.')
    return numbers, duplicates
