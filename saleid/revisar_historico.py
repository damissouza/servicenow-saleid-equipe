"""Completa pendências ou corrige histórico publicado, sem acessar o ServiceNow."""
import argparse
import sys
import processar_chamados as app
import historico_venda_ativa as history
from tabela_historico import review_table


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pendentes',action='store_true',help='Usa o fluxo anterior: quatro colunas e cobertura de todas as matrículas pendentes.')
    args=parser.parse_args()
    with app.base.execution_lock():
        if args.pendentes:
            path=app.ROOT/'saida'/history.PENDING
            if not path.exists():raise app.base.Stop('Nenhuma revisão do histórico pendente.')
            count=history.review_pending(app.ROOT)
            print(f'Histórico atualizado: {count} registros revisados. Nenhum chamado alterado.')
        else:
            review_table(app.ROOT)


if __name__=='__main__':
    try:main()
    except (app.base.Stop,OSError,ValueError,KeyError,EOFError,KeyboardInterrupt) as exc:
        print('Interrompido: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
