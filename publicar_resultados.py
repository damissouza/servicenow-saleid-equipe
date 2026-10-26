"""Entrada alternativa para conferir/publicar o historico; sem acesso ao ServiceNow."""
import argparse
from pathlib import Path
from saleid.publicar_site import SITE, FIELDS, LIMIT, SameSiteRedirect, read_payload, publish
from saleid import publicar_site as site

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conferir', action='store_true', help='Confere o arquivo local sem rede ou gravacao.')
    args = parser.parse_args()
    root = ROOT / 'saleid'
    if args.conferir:
        data = read_payload(root / 'saida/historico_venda_ativa.json', skip_incomplete=True)
        print(f'{len(data["rows"])} registros completos para publicar. Nenhum envio realizado.')
        return 0
    import sys
    sys.path.insert(0, str(root))
    import bulk_update as base
    with base.execution_lock():
        site.synchronize(root)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (site.PublicationPending, OSError, ValueError, KeyboardInterrupt, EOFError) as exc:
        raise SystemExit(str(exc)) from None
