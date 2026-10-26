"""Extrai somente o evento de atribuição que está visível na atividade do chamado."""
from datetime import datetime
import json
from pathlib import Path
import re

STAMP = '%d-%m-%Y %H:%M:%S'
EMPTY = {'', 'vazio', '(vazio)', 'empty', '(empty)', '-- vazio --', '-- none --', 'nenhum', '(nenhum)'}


def select_visible_assignment(events, opening, resolution):
    start, end = datetime.strptime(opening, STAMP), datetime.strptime(resolution, STAMP)
    candidates = []
    for event in events:
        try:
            date = datetime.strptime(event['date'], STAMP)
            value = event['value'].strip()
        except (KeyError, ValueError, TypeError, AttributeError):
            continue
        if start <= date <= end:
            candidates.append((date, value))
    if not candidates:
        return None
    latest = max(date for date, _ in candidates)
    values = {value for date, value in candidates if date == latest}
    if len(values) != 1:
        return None
    value = values.pop()
    if value.lower() in EMPTY:
        return None
    return latest.strftime(STAMP)


class ActivityReader:
    def __init__(self, context, directory, origin):
        self.context = context
        self.origin = origin
        self.page = None
        self.directory = Path(directory)
        self.cache_path = self.directory / 'cache_atividade.json'
        self.errors = 0
        self.incomplete = 0
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.cache = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.page and not self.page.is_closed():
            self.page.close()  # Only this reader's temporary tab.

    def read(self, table, ident, number, opening, resolution):
        previous = self.cache.get(ident)
        if previous and previous.get('number') == number and previous.get('opening') == opening and previous.get('resolution') == resolution:
            try:
                candidate = datetime.strptime(previous['assignment'], STAMP)
                if datetime.strptime(opening, STAMP) <= candidate <= datetime.strptime(resolution, STAMP):
                    return previous['assignment']
            except (KeyError, ValueError):
                pass
        if table not in {'incident', 'sc_req_item'} or not re.fullmatch('[0-9a-f]{32}', ident):
            raise ValueError('Registro de atividade inválido.')
        if self.page is None:
            self.page = self.context.new_page()
        try:
            from urllib.parse import urlsplit
            parsed = urlsplit(self.origin)
            if parsed.scheme != 'https' or not parsed.hostname:
                raise ValueError('Abra uma pagina HTTPS da instancia ServiceNow antes da coleta.')
            self.page.goto(f'{parsed.scheme}://{parsed.netloc}/{table}.do?sys_id={ident}', wait_until='domcontentloaded', timeout=60000)
            form = self.page.frame_locator('#gsft_main')
            identity = form.get_by_role('textbox', name='Número', exact=True)
            identity.wait_for(state='visible', timeout=45000)
            if identity.input_value() != number:
                raise ValueError('O número no formulário não confere com o JSON.')
            stream = form.locator('.sn-stream:not(.sn-form-stream-inline)')
            stream.wait_for(state='visible', timeout=30000)
            form.locator('.h-card').first.wait_for(state='visible', timeout=30000)
            for _ in range(20):
                more = form.get_by_role('button', name=re.compile(r'^(Carregar mais|Load more|Mostrar mais atividades|Show more activities)$', re.I))
                if more.count() and more.first.is_visible():
                    more.first.click()
                    continue
                break
            # Read rendered DOM only; no APIs, session tokens, hidden application state or writes.
            total_match = re.search(r'(?:Atividades|Activities)\s*:\s*([\d.,]+)', stream.inner_text(), re.I)
            data = form.locator('.h-card').evaluate_all('''cards => {
              const events=[];
              for(const card of cards){
                const date=card.querySelector('.date-calendar')?.innerText.trim();
                for(const row of card.querySelectorAll('.sn-widget-list-table > li')){
                  const label=row.children[0]?.innerText.trim();
                  if(label!=='Atribuição a'&&label!=='Assigned to')continue;
                  const cell=row.children[1];
                  const value=cell?.children[0]?.innerText??cell?.innerText;
                  if(date&&value!==undefined)events.push({date,value:value.trim()});
                }
              }
              return {events,rendered:cards.length};
            }''')
            data['total'] = int(re.sub(r'[.,]', '', total_match.group(1))) if total_match else None
            if data['total'] is None or data['rendered'] < data['total']:
                self.incomplete += 1
                return None
            assignment = select_visible_assignment(data['events'], opening, resolution)
            if assignment:
                self.cache[ident] = {'number': number, 'opening': opening, 'resolution': resolution, 'assignment': assignment}
                self.directory.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.cache, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.cache_path)
            return assignment
        except Exception:
            self.errors += 1
            return None
