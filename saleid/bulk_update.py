"""Atualização explícita de incidentes, com prévia e diário de execução local."""
from __future__ import annotations
# Permite executar diretamente os scripts nas pastas por função.
import sys as _sys
from pathlib import Path as _Path
_project_root = _Path(__file__).resolve().parent
_sys.path.insert(0, str(_project_root))


import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parent
FIELDS = 'sys_id,number,active,assigned_to,state,hold_reason,sys_mod_count,short_description'


class Stop(RuntimeError):
    pass


class HttpFailure(Stop):
    def __init__(self, method, table, status):
        self.method, self.table, self.status = method, table, status
        super().__init__(f'{method} {table}: HTTP {status}. Verifique sessão e permissões.')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    for attempt in range(5):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def raw(value):
    return str(value.get('value', '') if isinstance(value, dict) else value or '')


def display(value):
    return str(value.get('display_value', value.get('value', '')) if isinstance(value, dict) else value or '')


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value).strip().casefold())
                   if not unicodedata.combining(c))


def safe(value):
    value = str(value).strip()
    if not value or any(c in value for c in '^\r\n'):
        raise Stop('Valor vazio ou inválido para consulta.')
    return value


def sys_id(value):
    if not re.fullmatch(r'[0-9a-f]{32}', str(value)):
        raise Stop(f'Identificador ServiceNow inválido: {value!r}')
    return value


def parse_numbers(text):
    numbers, duplicates = [], []
    for token in re.split(r'[\s,;]+', text.strip()):
        if not token:
            continue
        number = token.upper()
        if not re.fullmatch(r'INC\d{7,}', number):
            raise Stop(f'Número inválido: {token!r}. Use apenas incidentes INC.')
        if number in numbers:
            duplicates.append(number)
        else:
            numbers.append(number)
    if not numbers:
        raise Stop('Lista vazia.')
    return numbers, duplicates


def load_config(path):
    config = read_json(path)
    url = urlsplit(config['instance_url'].strip())
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise Stop('Preencha instance_url em config.json com a URL HTTPS do ServiceNow.')
    config['origin'] = f'https://{url.netloc}'
    if config.get('connection_mode', 'cdp') not in ('cdp', 'persistent'):
        raise Stop('connection_mode deve ser cdp ou persistent.')
    cdp = urlsplit(config.get('cdp_url', 'http://127.0.0.1:9222'))
    if cdp.scheme != 'http' or cdp.hostname not in ('127.0.0.1', 'localhost') or cdp.username or cdp.password:
        raise Stop('cdp_url deve apontar para o Chrome local em localhost/127.0.0.1.')
    if config['browser'] not in ('chrome', 'chromium'):
        raise Stop('browser deve ser chrome ou chromium.')
    for field in ('comment', 'work_note'):
        if not isinstance(config[field], str) or not config[field].strip():
            raise Stop(f'{field} não pode ficar vazio.')
    if config['max_incidents'] <= 0 or config['delay_seconds'] < 0 or config['plan_max_age_minutes'] <= 0:
        raise Stop('Limites de execução inválidos.')
    if not config['tags'] or len(config['tags']) != len(set(config['tags'])):
        raise Stop('Informe marcadores distintos.')
    return config


@contextmanager
def execution_lock():
    path = ROOT / '.execution.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Stop('Outra execução está aberta ou deixou .execution.lock. Consulte o README.')
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


class Client:
    def __init__(self, page, origin):
        self.page, self.origin = page, origin

    def evaluate_request(self, script, args, method, table):
        attempts = 3 if method == 'GET' else 1
        for attempt in range(attempts):
            try:
                return self.page.evaluate(script, args)
            except Exception as exc:
                transient = any(message in str(exc).lower() for message in (
                    'failed to fetch', 'aborterror', 'networkerror', 'execution context was destroyed'))
                if transient and attempt + 1 < attempts:
                    print(f'Falha de conexão na leitura de {table}; repetindo consulta ({attempt + 2}/{attempts}).')
                    time.sleep(attempt + 1)
                    continue
                if method == 'GET':
                    raise Stop(f'Falha na leitura de {table} pela sessão do navegador. '
                               'Atualize o Workspace no Brave, confirme login e conexão/VPN e tente novamente. '
                               'Esta consulta não realizou escrita.') from exc
                raise Stop(f'Falha de conexão durante {method} em {table}; resultado da escrita incerto. '
                           'Não houve reenvio. Confira saida/execution.json e o chamado no ServiceNow.') from exc

    def request(self, method, table, *, record_id=None, params=None, body=None):
        if table not in {'incident', 'sc_req_item', 'sc_task', 'sys_user', 'sys_choice', 'label', 'label_entry', 'sys_journal_field'}:
            raise Stop('Tabela não permitida.')
        if table == 'sc_task' and method != 'GET' and not (
                method == 'PATCH' and record_id and body and (
                    set(body) in ({'assigned_to'}, {'comments'}) or
                    (set(body) == {'comments', 'close_notes', 'state', 'active', 'assigned_to'} or
                     set(body) == {'comments', 'close_notes', 'state', 'active', 'assigned_to', 'u_resolution_code', 'u_resolution_annotation'}
                     and body.get('u_resolution_code') == 'resolution code'
                     and body.get('u_resolution_annotation') == '9f386b6787fa871089470e530cbb3526')
                    and body['state'] == '3' and body['active'] == 'false')
                and all(isinstance(v, str) and v.strip() for v in body.values())):
            raise Stop('SCTASK permite somente leitura ou encerramento concluído com campos conferidos.')
        if method == 'PATCH' and table not in {'incident', 'sc_req_item', 'sc_task'} or method == 'POST' and table != 'label_entry':
            raise Stop('Operação de escrita não permitida.')
        if table == 'sc_req_item' and (method not in {'GET', 'PATCH'} or
                method == 'PATCH' and (not body or not (
                    set(body) == {'comments'} or
                    set(body) == {'state', 'active', 'close_notes', 'assigned_to', 'comments'}
                    and body['state'] == '3' and body['active'] == 'false'))):
            raise Stop('RITM permite leitura, comentário ou encerramento concluído com campos conferidos.')
        path = '/api/now/table/' + table
        if record_id:
            path += '/' + sys_id(record_id)
        url = self.origin + path + '?' + urlencode(params or {})
        # A chamada é limitada à mesma origem autenticada. Escritas não têm retry.
        response = self.evaluate_request('''async ({url, method, body}) => {
            if (new URL(url).origin !== location.origin) throw Error('Origem de login diferente');
            const token = window.g_ck || document.querySelector('meta[name="sysparm_ck"]')?.content;
            if (!token && method !== 'GET') throw Error('Token de sessão indisponível');
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 60000);
            try {
                const response = await fetch(url, {
                    method, credentials:'same-origin', redirect:'error', signal:controller.signal,
                    headers:{'Accept':'application/json','Content-Type':'application/json',
                             ...(token ? {'X-UserToken':token} : {})},
                    ...(body === null ? {} : {body:JSON.stringify(body)})
                });
                return {status:response.status, text:await response.text()};
            } finally { clearTimeout(timer); }
        }''', {'url': url, 'method': method, 'body': body}, method, table)
        if not 200 <= response['status'] < 300:
            failure = HttpFailure(method, table, response['status'])
            failure.response_text = response.get('text', '')[:3000]
            raise failure
        try:
            payload = json.loads(response['text'])
        except ValueError:
            raise Stop('Resposta não JSON. A sessão pode ter expirado.')
        if 'result' not in payload:
            raise Stop(f'Resposta inesperada de {table}.')
        return payload['result']

    def rows(self, table, query, fields, limit=1000):
        rows = self.request('GET', table, params={
            'sysparm_query': query, 'sysparm_fields': fields,
            'sysparm_limit': str(limit), 'sysparm_display_value': 'all',
            'sysparm_exclude_reference_link': 'true'})
        if not isinstance(rows, list) or len(rows) >= limit:
            raise Stop(f'Resposta inválida ou limite atingido em {table}; não continuar com dados truncados.')
        return rows

    def incident(self, number):
        rows = self.rows('incident', 'number=' + safe(number), FIELDS, 3)
        rows = [r for r in rows if raw(r.get('number')) == number]
        if len(rows) != 1:
            raise Stop(f'{number}: não encontrado de forma única ou sem acesso.')
        record = rows[0]
        if any(field not in record for field in FIELDS.split(',')):
            raise Stop(f'{number}: campos necessários não estão visíveis pela API.')
        if raw(record['active']) not in ('true', '1'):
            raise Stop(f'{number}: incidente inativo; não será reaberto.')
        sys_id(raw(record['sys_id']))
        return record

    def tags(self, incident_id):
        return self.rows('label_entry', f'table=incident^table_key={sys_id(incident_id)}',
                         'sys_id,label,table,table_key')

    def journal(self, incident_id, field):
        if field not in ('comments', 'work_notes'):
            raise Stop('Campo de diário inválido.')
        return self.rows('sys_journal_field',
                         f'element_id={sys_id(incident_id)}^element={field}^ORDERBYDESCsys_created_on',
                         'sys_id,element_id,element,value', limit=10000)


@contextmanager
def connected(config, prompt=True, source_url=None):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Stop('Instale as dependências: python -m pip install -r requirements.txt')
    profile = Path(config['profile_dir'])
    if not profile.is_absolute():
        profile = ROOT / profile
    with sync_playwright() as playwright:
        owned = config.get('connection_mode', 'cdp') == 'persistent'
        if owned:
            context = playwright.chromium.launch_persistent_context(
                str(profile), channel='chrome' if config['browser'] == 'chrome' else None,
                headless=False, no_viewport=True)
        else:
            try:
                browser = playwright.chromium.connect_over_cdp(config['cdp_url'])
            except Exception as exc:
                raise Stop('Não consegui conectar ao Chrome na porta 9222. Abra-o como no seu script de matrícula.') from exc
            if not browser.contexts:
                raise Stop('Chrome sem contexto disponível.')
            context = browser.contexts[0]
        try:
            if owned:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(config['origin'] + '/now/sow/home', wait_until='domcontentloaded')
            if prompt:
                input('Abra o Workspace ServiceNow e conclua login/MFA. Quando carregar, pressione Enter aqui: ')
            pages = [p for p in context.pages if not p.is_closed() and
                     f'{urlsplit(p.url).scheme}://{urlsplit(p.url).netloc}' == config['origin']]
            if not pages:
                raise Stop('Nenhuma página da instância autenticada foi encontrada.')
            if source_url is not None:
                pages = [p for p in pages if p.url == source_url]
                if not pages:
                    raise Stop('A página original do Workspace não está disponível.')
            # As guias internas do Workspace não são novas pages. Não abrir, navegar ou fechar nenhuma.
            page = pages[0] if source_url is not None else pages[-1]
            surface = None
            for frame in page.frames:
                if f'{urlsplit(frame.url).scheme}://{urlsplit(frame.url).netloc}' != config['origin']:
                    continue
                try:
                    has_token = frame.evaluate('Boolean(window.g_ck || document.querySelector(\'meta[name="sysparm_ck"]\')?.content)')
                except Exception:
                    continue
                if has_token:
                    surface = frame
                    break
            if surface is None:
                raise Stop('Token da sessão não acessível neste Workspace. Nenhuma alteração feita; será necessário adaptar a integração.')
            yield Client(surface, config['origin'])
        finally:
            if owned:
                context.close()
            # Em CDP, sair do Playwright desconecta o cliente sem fechar o Chrome do usuário.


def choice(client, element, labels, override=None, state=None):
    rows = client.rows('sys_choice', f'nameINincident,task^element={element}^inactive=false',
                       'name,element,label,value,dependent_value,language')
    wanted = {normalized(label) for label in labels}
    candidates = [r for r in rows if normalized(display(r.get('label'))) in wanted
                  and (not raw(r.get('dependent_value')) or raw(r['dependent_value']) == state)]
    incident_choices = [r for r in candidates if raw(r.get('name')) == 'incident']
    candidates = incident_choices or candidates
    values = {raw(r['value']) for r in candidates}
    if override is not None:
        values &= {str(override)}
    if len(values) != 1:
        available = [(raw(r.get('value')), display(r.get('label'))) for r in rows]
        raise Stop(f'Não foi possível mapear {element} para {labels}. Opções visíveis: {available}')
    return values.pop()


def pair_from_record(record, config):
    """Só aceita códigos acompanhados dos rótulos esperados na resposta da origem."""
    values = []
    for field, labels in [('state', config['state_labels']), ('hold_reason', config['hold_reason_labels'])]:
        value = record.get(field)
        if not isinstance(value, dict) or 'display_value' not in value or 'value' not in value:
            return None
        if normalized(value['display_value']) not in {normalized(label) for label in labels}:
            return None
        code = raw(value)
        if not code or not re.fullmatch(r'-?\d+', code):
            return None
        override = config.get(field + '_value')
        if override is not None and code != str(override):
            return None
        values.append(code)
    return tuple(values)


def choices_from_incidents(client, config, assignee_id):
    reference = config.get('reference_incident')
    fields = 'sys_id,number,assigned_to,active,state,hold_reason'
    if reference:
        numbers, duplicates = parse_numbers(reference)
        if len(numbers) != 1 or duplicates:
            raise Stop('reference_incident deve conter exatamente um número INC.')
        reference = numbers[0]
        records = client.rows('incident', 'number=' + reference, fields, 3)
        records = [record for record in records if raw(record.get('number')) == reference]
        if len(records) != 1:
            raise Stop('Incidente de referência não encontrado de forma única ou sem acesso.')
    else:
        # Amostra limitada de chamados da própria responsável; não é uma exportação geral.
        records = client.request('GET', 'incident', params={
            'sysparm_query':f'assigned_to={sys_id(assignee_id)}^active=true^hold_reasonISNOTEMPTY^ORDERBYDESCsys_updated_on',
            'sysparm_fields':fields, 'sysparm_limit':'200', 'sysparm_display_value':'all',
            'sysparm_exclude_reference_link':'true'})
        if not isinstance(records, list):
            raise Stop('Resposta inesperada ao procurar um incidente de referência.')
        records = [record for record in records if raw(record.get('assigned_to')) == assignee_id]
    candidates = []
    for record in records:
        pair = pair_from_record(record, config)
        if pair and raw(record.get('active')) in ('true', '1'):
            candidates.append((record, pair))
    pairs = {pair for _, pair in candidates}
    if len(pairs) != 1:
        raise Stop('Não encontrei códigos inequívocos para Em espera / Aguardando fornecedor. '
                   'Informe em reference_incident no config.json um INC ativo que já esteja nessa situação. '
                   'Ele será somente lido, sem entrar no lote.')
    record, pair = candidates[0]
    client.choice_evidence = {
        'source':'incident_display_values', 'number':raw(record.get('number')),
        'sys_id':sys_id(raw(record.get('sys_id'))),
        'state':record['state'], 'hold_reason':record['hold_reason']}
    print('Estado e motivo conferidos pelo incidente de referência ' + raw(record['number']) + '.')
    return pair


def resolve_state_and_reason(client, config, assignee_id):
    if config.get('reference_incident'):
        return choices_from_incidents(client, config, assignee_id)
    try:
        state = choice(client, 'state', config['state_labels'], config.get('state_value'))
        reason = choice(client, 'hold_reason', config['hold_reason_labels'], config.get('hold_reason_value'), state)
        client.choice_evidence = {'source':'sys_choice'}
        return state, reason
    except HttpFailure as exc:
        if exc.table != 'sys_choice' or exc.status != 403:
            raise
        print('Leitura de sys_choice negada. Conferindo rótulos em incidentes acessíveis da responsável.')
        return choices_from_incidents(client, config, assignee_id)


def resolve_targets(client, config):
    email = safe(config['assignee_email'])
    users = client.rows('sys_user', f'email={email}^active=true', 'sys_id,email,name,active', 100)
    users = [u for u in users if raw(u.get('email')).casefold() == email.casefold()
             and raw(u.get('active')) in ('true', '1')]
    if len(users) != 1:
        raise Stop('E-mail não identifica exatamente um usuário ativo.')
    assignee_id = sys_id(raw(users[0]['sys_id']))
    state, reason = resolve_state_and_reason(client, config, assignee_id)
    tags = {}
    for name in config['tags']:
        rows = client.rows('label', 'name=' + safe(name), 'sys_id,name,owner', 100)
        rows = [r for r in rows if raw(r.get('name')) == name]
        specified = config.get('tag_ids', {}).get(name)
        if specified:
            rows = [r for r in rows if raw(r['sys_id']) == sys_id(specified)]
        if len(rows) != 1:
            raise Stop(f'Marcador {name!r} ausente/ambíguo. Confira no ServiceNow e informe tag_ids no config.json, se necessário.')
        tags[name] = sys_id(raw(rows[0]['sys_id']))
    return {'assigned_to': assignee_id, 'state': state, 'hold_reason': reason}, tags


def journal_snapshot(client, record_id):
    return {field: client.journal(record_id, field) for field in ('comments', 'work_notes')}


def ensure_allowed_state(record, config):
    allowed = config.get('allowed_current_states')
    allowed_labels = config.get('allowed_current_state_labels', [])
    state = record.get('state')
    label_matches = (isinstance(state, dict) and bool(state.get('display_value'))
                     and normalized(state['display_value']) in {normalized(label) for label in allowed_labels})
    if allowed is not None and raw(state) not in allowed and not label_matches:
        raise Stop(f'{raw(record.get("number"))}: estado atual não permitido para este lote '
                   f'({display(record.get("state"))}). Nenhuma escrita será iniciada neste item.')


def visible_one(locator, description):
    matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
    if len(matches) != 1:
        raise Stop(f'{description}: esperado um controle visível, encontrados {len(matches)}.')
    return matches[0]


def tag_option_pattern(name):
    return re.compile(r'^' + re.escape(name) + r'(?:\s+(?:groups and users|grupos e usuarios|grupos e usuários))?$', re.I)


def click_tag_suggestion(page, control, name, tag_id=None):
    # O Workspace pode incluir a descrição de compartilhamento no nome acessível.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if tag_id is not None:
            # O dropdown hoisted renderiza a opção clicável em outro shadow root.
            # O aria-controls aponta para um proxy de 1px; não clicar nesse proxy.
            actual = page.locator('[role="option"][id="' + sys_id(tag_id) + '"]')
            matches = [actual.nth(i) for i in range(actual.count()) if actual.nth(i).is_visible()]
            if len(matches) > 1:
                raise Stop('Mais de uma opção real para o identificador do marcador; clique bloqueado.')
            if len(matches) == 1:
                label = re.sub(r'\s+', ' ', matches[0].inner_text()).strip()
                if tag_option_pattern(name).fullmatch(label) is None:
                    raise Stop('Nome e identificador da sugestão não correspondem ao marcador esperado.')
                matches[0].click(timeout=5000)
                return
            page.wait_for_timeout(200)
            continue
        root = page
        controlled = control.get_attribute('aria-controls') or control.get_attribute('aria-owns')
        if controlled:
            roots = []
            for identifier in controlled.split():
                container = page.locator('[id=' + json.dumps(identifier) + ']')
                roots.extend(container.nth(i) for i in range(container.count()) if container.nth(i).is_visible())
            if len(roots) == 1:
                root = roots[0]
            elif len(roots) > 1:
                raise Stop('Mais de um painel associado ao campo de marcadores; nenhuma opção foi selecionada.')
        candidates = [root.get_by_role('option', name=tag_option_pattern(name)),
                      root.get_by_text(name, exact=True)]
        for locator in candidates:
            visible = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
            # Não confundir texto/container aninhados da mesma sugestão com duas opções.
            matches = []
            for candidate in visible:
                contains_another = False
                for other in visible:
                    handle = other.element_handle()
                    try:
                        if handle is not None and candidate.evaluate(
                            '(el, other) => { if (el === other) return false; '
                            'for (let node = other; node; node = node.parentNode || node.host) '
                            '{ if (node === el) return true; } return false; }', handle):
                            contains_another = True
                            break
                    finally:
                        if handle is not None:
                            handle.dispose()
                if not contains_another:
                    matches.append(candidate)
            if len(matches) == 1:
                matches[0].click(timeout=5000)
                return
            if len(matches) > 1:
                raise Stop(f'Mais de uma sugestão visível para {name!r}; nenhuma foi selecionada.')
        page.wait_for_timeout(200)
    raise Stop(f'O Workspace não apresentou uma opção inequívoca para {name!r}. '
               'Deixe o painel aberto e rode diagnosticar.py para conferir as sugestões. Nenhuma opção foi selecionada.')


def open_workspace_incident(client, number, record_id):
    """Abre um único incidente e verifica o formulário, sem pedir abertura manual."""
    page = getattr(client.page, 'page', client.page)
    tab = page.locator('a[role="tab"]').filter(has_text=re.compile('^' + re.escape(number) + '$'))
    opened = not bool(tab.count())
    if not opened:
        visible_one(tab, 'Guia ' + number).click()
    else:
        if page.locator('[aria-label^="Fechar guia INC"], [aria-label^="Fechar guia RITM"], [aria-label^="Fechar guia SCTASK"]').count() >= 8:
            raise Stop('Workspace no limite de guias; nenhuma nova guia foi aberta.')
        listing = page.locator('a#tab_0')
        if listing.count():
            visible_one(listing, 'Guia Lista').click()
        link = page.locator('a.link-cell-link').filter(has_text=re.compile('^' + re.escape(number) + '$'))
        if link.count():
            visible_one(link, 'Link ' + number).click()
        else:
            # A rota pública do Workspace permite abrir itens fora da página atual da lista.
            page.goto(client.origin + '/now/sow/record/incident/' + sys_id(record_id),
                      wait_until='domcontentloaded', timeout=30000)
    details = page.get_by_role('tab', name='Detalhes', exact=True)
    details.first.wait_for(state='visible', timeout=20000)
    visible_one(details, 'Detalhes').click()
    number_field = page.locator('input[name="number"]')
    number_field.first.wait_for(state='visible', timeout=15000)
    if visible_one(number_field, 'Número do incidente').input_value().strip() != number:
        raise Stop('O formulário visível não corresponde ao incidente do lote.')
    return opened


def workspace_tag(client, number, name, tag_id):
    """Usa controles públicos do Workspace; nunca cria uma tag global nem escolhe por posição."""
    page = getattr(client.page, 'page', client.page)
    opened = open_workspace_incident(client, number, raw(client.incident(number)['sys_id']))
    # Conferência do número do formulário antes de tocar em qualquer marcador.
    details = page.get_by_role('tab', name='Detalhes', exact=True)
    try:
        details.first.wait_for(state='visible', timeout=20000)
    except Exception as exc:
        raise Stop('A guia Detalhes não carregou em 20 segundos. Abra o incidente e aguarde o formulário antes de retomar.') from exc
    visible_one(details, 'Detalhes').click()
    number_field = page.locator('input[name="number"]')
    number_field.first.wait_for(state='visible', timeout=15000)
    if visible_one(number_field, 'Número do incidente').input_value().strip() != number:
        raise Stop('O formulário visível não corresponde ao incidente do lote.')
    field = page.get_by_role('combobox', name='Adicionar marcador', exact=True)
    if not any(field.nth(i).is_visible() for i in range(field.count())):
        visible_one(page.get_by_role('button', name=re.compile('^Exibir e editar marcadores')), 'Painel de marcadores').click()
    field.first.wait_for(state='visible', timeout=10000)
    control = visible_one(field, 'Adicionar marcador')
    control.fill(name)
    click_tag_suggestion(page, control, name, tag_id)
    control.press('Escape')
    return opened


def close_owned_tab(client, number):
    page = getattr(client.page, 'page', client.page)
    selector = '[aria-label=' + json.dumps('Fechar guia ' + number) + ']'
    close = page.locator(selector)
    visible_one(close, 'Fechar guia criada pelo programa').click(timeout=5000)
    close.first.wait_for(state='detached', timeout=5000)



def resumable_tag_failure(previous, config):
    tag_click_timeout = (
        previous.get('operation') == 'adding_tag:Atendas'
        and previous.get('added_tags') == []
        and str(previous.get('error', '')).startswith('TimeoutError: Locator.click: Timeout'))
    known_before_selection = (
        previous.get('added_tags') == []
        and previous.get('operation') == 'adding_tag:Atendas'
        and previous.get('error') in {
            'Stop: Detalhes: esperado um controle visível, encontrados 0.',
            "Stop: Mais de uma sugestão visível para 'Atendas'; nenhuma foi selecionada.",
            "Stop: O Workspace não apresentou uma opção inequívoca para 'Atendas'. Deixe o painel aberto e rode diagnosticar.py para conferir as sugestões. Nenhuma opção foi selecionada.",
            'Stop: A guia Detalhes não carregou em 20 segundos. Abra o incidente e aguarde o formulário antes de retomar.'})
    return (config.get('tag_write_mode') == 'workspace'
            and previous.get('status') == 'uncertain_or_partial'
            and previous.get('patch_sent') is False
            and (previous.get('error') == 'Stop: Não foi possível confirmar os marcadores.'
                 or known_before_selection or tag_click_timeout))


def preview(client, config, numbers):
    targets, tags = resolve_targets(client, config)
    items = []
    for index, number in enumerate(numbers, 1):
        print(f'Conferindo {index}/{len(numbers)}: {number}')
        record = client.incident(number)
        ensure_allowed_state(record, config)
        record_id = raw(record['sys_id'])
        existing = client.tags(record_id)
        journal_snapshot(client, record_id)  # exige leitura para conferir o resultado depois
        items.append({'number': number, 'sys_id': record_id, 'before': record,
                      'existing_tags': existing})
    plan = {'created_at': datetime.now(timezone.utc).isoformat(), 'config_hash': digest(config),
            'choice_evidence':getattr(client, 'choice_evidence', None),
            'origin': config['origin'], 'targets': targets, 'tags': tags, 'items': items,
            'comment': config['comment'], 'work_note': config['work_note']}
    save_json(ROOT / 'saida' / 'preview.json', plan)
    print(json.dumps({'quantidade':len(items), 'destino':targets, 'marcadores':tags,
                      'comentario':config['comment'], 'anotacao':config['work_note']}, ensure_ascii=False, indent=2))
    print('Prévia salva em saida/preview.json. Nenhum chamado foi alterado.')
    return plan


def validate_plan(plan, config, numbers):
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan['created_at'])).total_seconds()
    if not 0 <= age <= config['plan_max_age_minutes'] * 60:
        raise Stop('Prévia expirada. Gere uma nova prévia.')
    if plan['config_hash'] != digest(config) or plan['origin'] != config['origin']:
        raise Stop('Configuração mudou. Gere nova prévia.')
    if [item['number'] for item in plan['items']] != numbers:
        raise Stop('Lista mudou. Gere nova prévia.')


def verify_journals(client, record_id, before, config):
    for attempt in range(3):
        ok = True
        readable_entries = 0
        for field, text in [('comments', config['comment']), ('work_notes', config['work_note'])]:
            prior = {raw(r['sys_id']) for r in before[field]}
            rows = client.journal(record_id, field)
            readable_entries += len(rows)
            ok &= any(raw(r['sys_id']) not in prior and raw(r.get('value')).replace('\r\n', '\n') == text
                      for r in rows)
        if ok:
            return 'api_verified'
        if attempt < 2:
            time.sleep(1)
    if readable_entries == 0 and config.get('allow_pending_journal_verification', False):
        return 'unavailable_pending_review'
    raise Stop('Não foi possível comprovar as duas novas entradas de diário. Não reenviar automaticamente.')


def apply(client, config, numbers, plan):
    validate_plan(plan, config, numbers)
    targets, tags = resolve_targets(client, config)
    if targets != plan['targets'] or tags != plan['tags']:
        raise Stop('Mapeamentos mudaram. Gere nova prévia.')
    ledger_path = ROOT / 'saida' / 'execution.json'
    ledger = read_json(ledger_path) if ledger_path.exists() else {}
    # O diário se mantém entre novas prévias: resultado incerto nunca é repetido.
    batch_key = digest({'origin':config['origin'], 'targets':targets, 'tags':tags,
                        'comment':config['comment'], 'work_note':config['work_note']})
    batch = ledger.setdefault(batch_key, {})
    pending = []
    for item in plan['items']:
        previous = batch.get(item['number'])
        resume_tags = bool(previous and resumable_tag_failure(previous, config))
        processed = previous and previous['status'] in ('verified', 'fields_verified_journals_pending')
        if previous and not processed and not resume_tags:
            raise Stop(f'{item["number"]}: execução anterior incerta/parcial. Confira execution.json e o ServiceNow antes de prosseguir.')
        if not previous or resume_tags:
            current = client.incident(item['number'])
            ensure_allowed_state(current, config)
            if raw(current['sys_id']) != item['sys_id'] or raw(current['sys_mod_count']) != raw(item['before']['sys_mod_count']):
                raise Stop(f'{item["number"]}: mudou desde a prévia. Gere nova prévia.')
            if resume_tags:
                if previous.get('sys_id') != item['sys_id'] or any(
                    raw(current.get(field)) != raw(previous['before'].get(field))
                    for field in ('sys_mod_count','state','hold_reason','assigned_to')):
                    raise Stop('O incidente da tentativa parcial mudou. Retomada automática bloqueada.')
                print(item['number'] + ': retomada da etapa de marcadores; nenhum PATCH havia sido enviado.')
            pending.append(item)
    if not pending:
        print('Todos os itens deste lote já foram processados no diário local; nada será reenviado. Confira eventuais textos pendentes de revisão.')
        return
    phrase = f'APLICAR {len(pending)}'
    print(f'Atualizar {len(pending)} incidentes para {config["assignee_email"]}.')
    print('Estado:', config['state_labels'][0], '| Motivo:', config['hold_reason_labels'][0])
    print('Marcadores:', ', '.join(config['tags']))
    print('Comentário:\n' + config['comment'] + '\nAnotação:\n' + config['work_note'])
    print('Números: ' + ', '.join(item['number'] for item in pending))
    if input(f'Digite {phrase} para executar: ').strip() != phrase:
        raise Stop('Execução cancelada; nenhuma escrita iniciada.')
    for item in pending:
        number, record_id = item['number'], item['sys_id']
        current = client.incident(number)
        ensure_allowed_state(current, config)
        if raw(current['sys_id']) != record_id or raw(current['sys_mod_count']) != raw(item['before']['sys_mod_count']):
            raise Stop(f'{number} mudou enquanto o lote era processado. Interrompido.')
        journals = journal_snapshot(client, record_id)
        entry = {'status':'started', 'started_at':datetime.now(timezone.utc).isoformat(),
                 'sys_id':record_id, 'before':current, 'added_tags':[], 'patch_sent':False}
        if number in batch:
            entry['previous_attempt'] = batch[number]
        batch[number] = entry
        save_json(ledger_path, ledger)
        try:
            owned_tab = False
            if config.get('tag_write_mode') == 'workspace':
                entry['operation'] = 'opening_workspace'
                save_json(ledger_path, ledger)
                print(number + ': abrindo no Workspace...', flush=True)
                owned_tab = open_workspace_incident(client, number, record_id)
            existing_ids = {raw(r.get('label')) for r in client.tags(record_id)}
            for name, tag_id in tags.items():
                if tag_id not in existing_ids:
                    entry['operation'] = 'adding_tag:' + name
                    save_json(ledger_path, ledger)
                    if config.get('tag_write_mode') == 'workspace':
                        owned_tab = workspace_tag(client, number, name, tag_id) or owned_tab
                    else:
                        client.request('POST', 'label_entry', body={
                            'label':tag_id, 'table':'incident', 'table_key':record_id})
                    for attempt in range(5):
                        if tag_id in {raw(r.get('label')) for r in client.tags(record_id)}:
                            break
                        if attempt == 4:
                            raise Stop('Não foi possível confirmar os marcadores.')
                        time.sleep(1)
                    entry['added_tags'].append(name)
                    save_json(ledger_path, ledger)
            if not set(tags.values()) <= {raw(r.get('label')) for r in client.tags(record_id)}:
                raise Stop('Não foi possível confirmar os marcadores.')
            entry['patch_sent'] = True  # registrar ANTES da chamada: falha de rede tem resultado incerto
            entry['operation'] = 'patch_incident'
            save_json(ledger_path, ledger)
            client.request('PATCH', 'incident', record_id=record_id,
                           body={**targets, 'comments':config['comment'], 'work_notes':config['work_note']})
            after = client.incident(number)
            if any(raw(after.get(key)) != value for key, value in targets.items()):
                raise Stop('Atualização não confirmada nos campos; uma regra/ACL pode ter interferido.')
            journal_verification = verify_journals(client, record_id, journals, config)
            status = 'verified' if journal_verification == 'api_verified' else 'fields_verified_journals_pending'
            entry.update(status=status, after=after, journal_verification=journal_verification,
                         finished_at=datetime.now(timezone.utc).isoformat())
            save_json(ledger_path, ledger)
            if status == 'verified':
                print(number + ': alterações verificadas.')
            else:
                print(number + ': campos e marcadores verificados; textos enviados, com conferência pendente na Atividade.')
            if owned_tab:
                try:
                    close_owned_tab(client, number)
                except Exception as close_error:
                    entry['workspace_close_error'] = str(close_error)
                    save_json(ledger_path, ledger)
                    raise Stop('Alterações confirmadas, mas a guia não fechou; lote pausado para não acumular guias.') from close_error
                print(number + ': guia fechada; seguindo para o próximo.', flush=True)
        except Exception as exc:
            entry.update(status=entry['status'] if entry.get('workspace_close_error') else 'uncertain_or_partial', error=type(exc).__name__ + ': ' + str(exc)[:500],
                         error_detail=str(exc))
            save_json(ledger_path, ledger)
            detail = str(exc)[:500]
            raise Stop(f'{number}: lote interrompido. Motivo: {detail} '
                       'Resultado registrado em saida/execution.json; não houve retry de escrita.') from exc
        time.sleep(config['delay_seconds'])
    print('Lote concluído. Relatório: saida/execution.json')
    unverified = [number for number in numbers if batch.get(number, {}).get('status') == 'fields_verified_journals_pending']
    if unverified:
        print(f'{len(unverified)} incidente(s) com textos pendentes de conferência na Atividade; não serão reenviados automaticamente.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['conferir-lista', 'prever', 'aplicar'])
    parser.add_argument('--lista', type=Path, default=ROOT / 'incidentes.txt')
    parser.add_argument('--colar', action='store_true', help='Cole os números; termine com linha vazia.')
    parser.add_argument('--config', type=Path, default=ROOT / 'config_conexao_historico_venda_ativa.json')
    parser.add_argument("--visivel", action="store_true", help="Conecta ao Brave aberto manualmente na porta 9222 (padrão).")
    args = parser.parse_args(argv)
    if not args.lista.is_absolute():
        args.lista = ROOT / args.lista
    if not args.config.is_absolute():
        args.config = ROOT / args.config
    try:
        if args.colar:
            print('Cole os incidentes, um por linha; finalize com uma linha vazia:')
            lines = []
            while True:
                line = input()
                if not line.strip():
                    break
                lines.append(line)
            text = '\n'.join(lines)
        else:
            text = args.lista.read_text(encoding='utf-8-sig')
        numbers, duplicates = parse_numbers(text)
        print(f'{len(numbers)} incidentes únicos. Duplicados removidos: {duplicates or "nenhum"}')
        if args.command == 'conferir-lista':
            print('\n'.join(numbers))
            return 0
        config = load_config(args.config)
        if len(numbers) > config['max_incidents']:
            raise Stop('Quantidade excede max_incidents configurado.')
        with execution_lock(), connected(config) as client:
            if args.command == 'prever':
                preview(client, config, numbers)
            else:
                apply(client, config, numbers, read_json(ROOT / 'saida' / 'preview.json'))
        return 0
    except (Stop, OSError, ValueError, KeyError) as exc:
        print('Interrompido: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('Interrompido. Se iniciou a aplicação, confira saida/execution.json antes de retomar.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
