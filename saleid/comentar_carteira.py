"""Dependencia copiada: somente busca inequívoca de usuario ativo por e-mail."""
import bulk_update as base


def resolve_user(client, config):
    email = base.safe(config['assignee_email'])
    rows = client.rows('sys_user', f'email={email}^active=true', 'sys_id,email,active', 100)
    rows = [r for r in rows if base.raw(r.get('email')).casefold() == email.casefold()
            and base.raw(r.get('active')) in ('true', '1')]
    if len(rows) != 1:
        raise base.Stop('Responsável não encontrado de forma única.')
    return base.sys_id(base.raw(rows[0]['sys_id']))
