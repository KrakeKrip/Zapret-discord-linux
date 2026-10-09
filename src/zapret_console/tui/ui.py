"""Widgets and event-loop state. Blocking work never touches widgets."""
import asyncio
from contextlib import nullcontext
import re

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Select, Static, TabbedContent, TabPane, TextArea

from .. import core


class Confirm(ModalScreen[bool]):
    DEFAULT_CSS = """
    Confirm { align: center middle; background: #080c10 80%; }
    Confirm > Vertical { width: 64; max-width: 95%; height: auto; padding: 1 2; border: round #73e2c2; background: #162129; }
    Confirm Horizontal { height: auto; margin-top: 1; }
    Confirm Button { margin-right: 2; }
    """
    BINDINGS = [('escape', 'cancel', 'Отмена')]

    def __init__(self, message):
        super().__init__()
        self.message = message

    def compose(self):
        with Vertical():
            yield Static(self.message, markup=False)
            with Horizontal():
                yield Button('Отмена', id='cancel')
                yield Button('Подтвердить', variant='warning', id='confirm')

    def on_mount(self):
        self.query_one('#cancel').focus()

    def on_button_pressed(self, event):
        if not event.button.disabled:
            self.dismiss(event.button.id == 'confirm')

    def action_cancel(self):
        self.dismiss(False)


class ProfileName(ModalScreen[str | None]):
    DEFAULT_CSS = """
    ProfileName { align: center middle; background: #080c10 80%; }
    ProfileName > Vertical { width: 64; max-width: 95%; height: auto; padding: 1 2; border: round #73e2c2; background: #162129; }
    ProfileName Horizontal { height: auto; margin-top: 1; }
    ProfileName Button { margin-right: 2; }
    """
    BINDINGS = [('escape', 'cancel', 'Отмена')]

    def compose(self):
        with Vertical():
            yield Static('Сохранить текущую настройку', markup=False)
            yield Input(placeholder='Имя профиля', id='profile-name')
            yield Static(core.PROFILE_NAME_HINT, markup=False)
            with Horizontal():
                yield Button('Отмена', id='cancel')
                yield Button('Сохранить', variant='success', id='save-name', disabled=True)

    allowed = True

    def on_mount(self):
        self.query_one(Input).focus()

    def on_input_changed(self, event):
        self.query_one('#save-name', Button).disabled = not self.allowed or not bool(re.fullmatch(core.PROFILE_NAME, event.value))

    def on_input_submitted(self, event):
        if not self.query_one('#save-name', Button).disabled:
            self.dismiss(event.value)

    def on_button_pressed(self, event):
        if not event.button.disabled:
            self.dismiss(self.query_one(Input).value if event.button.id == 'save-name' else None)

    def action_cancel(self):
        self.dismiss(None)


class ZapretApp(App):
    TITLE = 'Zapret Console'
    SUB_TITLE = 'Терминальное управление'
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding('ctrl+q', 'quit', 'Выход', priority=True),
                Binding('ctrl+c', 'quit', show=False, priority=True),
                Binding('f5', 'refresh', 'Обновить')]
    CSS = """
    Screen { background: #0d1318; color: #ecf2f5; }
    Header, Footer { background: #162129; }
    TabPane { padding: 1 2; }
    .actions { height: auto; layout: horizontal; overflow-x: auto; margin: 1 0; }
    .actions Button { margin-right: 1; min-width: 14; }
    #service, #connection, #autostart, #current-strategy, #profile-detail { padding: 1; background: #162129; margin-bottom: 1; }
    #bottom-bar { dock: bottom; height: auto; }
    Footer { dock: none; }
    #event { height: auto; max-height: 3; padding: 0 1; background: #162129; }
    TextArea { height: 1fr; border: round #293943; }
    Select, Input { margin-bottom: 1; }
    Checkbox { height: auto; margin-bottom: 1; }
    """

    def __init__(self, backend=None):
        super().__init__()
        from ..client import Backend
        self.backend = backend or Backend(mode='terminal')
        self.snapshot = {}
        self.profile_rows = {}
        self.strategy_names = []
        self.pending = None
        self.closing = False
        self.generation = 0
        self.last_event = 'Читаем состояние…'
        self._poll = None

    def compose(self):
        yield Header()
        with TabbedContent(initial='home', id='pages'):
            with TabPane('Главная', id='home'):
                with VerticalScroll():
                    yield Static('Читаем состояние…', id='service', markup=False)
                    yield Static('Настройки ещё не прочитаны', id='connection', markup=False)
                    yield Static('Автозапуск: неизвестно', id='autostart', markup=False)
                    with Horizontal(classes='actions'):
                        yield Button('Запустить', variant='success', id='service-action')
                        yield Button('Перезапустить', id='restart')
                        yield Button('Автозапуск', id='autostart-action')
                    yield Static('Состояние сервиса не подтверждает доступность Discord. Закрытие TUI не останавливает сервис.', markup=False)
            with TabPane('Профили', id='profiles'):
                with VerticalScroll():
                    yield Select([], prompt='Выберите профиль', id='profile-select')
                    yield Static('Пока нет профилей', id='profile-detail', markup=False)
                    with Horizontal(classes='actions'):
                        yield Button('Сохранить…', variant='success', id='profile-save')
                        yield Button('Восстановить', id='profile-restore')
                        yield Button('Заменить…', id='profile-replace')
                        yield Button('Удалить…', variant='error', id='profile-delete')
            with TabPane('Стратегии', id='strategies'):
                with VerticalScroll():
                    yield Static('Текущая стратегия: неизвестно', id='current-strategy', markup=False)
                    yield Input(placeholder='Поиск стратегии', id='strategy-search')
                    yield Select([], prompt='Выберите стратегию', id='strategy-select')
                    yield Button('Применить', variant='success', id='strategy-apply')
                    yield Static('Остальные параметры подключения сохраняются.', markup=False)
            with TabPane('Диагностика', id='diagnostics'):
                yield Checkbox('Проверить firewall с sudo', id='diagnostic-auth')
                with Horizontal(classes='actions'):
                    yield Button('Проверить Discord', variant='success', id='diagnose')
                    yield Button('Копировать', id='copy-diagnostic')
                yield TextArea(read_only=True, id='diagnostic-report')
            with TabPane('Журнал', id='journal'):
                yield Static('До 100 последних записей, с текущими правами пользователя.', markup=False)
                with Horizontal(classes='actions'):
                    yield Button('Обновить журнал', variant='success', id='journal-refresh')
                    yield Button('Копировать', id='copy-journal')
                yield TextArea(read_only=True, id='journal-report')
        with Vertical(id='bottom-bar'):
            yield Static(self.last_event, id='event', markup=False)
            yield Footer()

    def on_mount(self):
        self._poll = self.set_interval(3, self.action_refresh)
        self.action_refresh()

    def show_event(self, text):
        self.last_event = text
        self.query_one('#event', Static).update(text)

    def controls(self):
        busy = self.pending is not None or self.closing
        can_write = self.snapshot.get('revision') is not None
        for button in self.query(Button):
            if button.id and button.id.startswith('copy-'):
                continue
            button.disabled = busy
        for name in ('profile-save', 'profile-restore', 'profile-replace', 'profile-delete', 'strategy-apply'):
            self.query_one('#' + name, Button).disabled |= not can_write
        profile = self.query_one('#profile-select', Select).value
        entry = self.profile_rows.get(profile)
        for name in ('profile-restore', 'profile-replace', 'profile-delete'):
            self.query_one('#' + name, Button).disabled |= entry is None
        self.query_one('#profile-restore', Button).disabled |= bool(entry and entry.get('config') is None)
        strategy = self.query_one('#strategy-select', Select).value
        self.query_one('#strategy-apply', Button).disabled |= strategy is Select.NULL or strategy == (self.snapshot.get('config') or {}).get('strategy')
        self.query_one('#diagnostic-auth', Checkbox).disabled = busy
        self.query_one('#copy-diagnostic', Button).disabled = self.closing or not self.query_one('#diagnostic-report', TextArea).text
        self.query_one('#copy-journal', Button).disabled = self.closing or not self.query_one('#journal-report', TextArea).text
        if isinstance(self.screen, ProfileName) and self.screen.is_mounted:
            self.screen.allowed = not busy and can_write
            value = self.screen.query_one(Input).value
            self.screen.query_one('#save-name', Button).disabled = not self.screen.allowed or not bool(re.fullmatch(core.PROFILE_NAME, value))
        elif isinstance(self.screen, Confirm) and self.screen.is_mounted:
            self.screen.query_one('#confirm', Button).disabled = busy or not can_write

    def action_refresh(self):
        self.schedule('snapshot', lambda: (self.backend.snapshot(), self.backend.strategies()))

    def schedule(self, kind, function, auth=False):
        if self.pending is not None or self.closing:
            return False
        self.generation += 1
        generation = self.generation
        self.pending = asyncio.create_task(self.execute(kind, function, auth, generation))
        self.controls()
        if kind != 'snapshot':
            self.show_event('Ожидание операции…')
        return True

    async def execute(self, kind, function, auth, generation):
        try:
            # sudo owns a restored terminal; UI never collects passwords.
            context = self.suspend() if auth and getattr(self.backend, 'requires_terminal', False) else nullcontext()
            with context:
                result = await asyncio.to_thread(function)
            if generation != self.generation:
                return
            if kind == 'snapshot':
                self.apply_snapshot(*result)
            elif kind == 'mutation':
                if result['ok']:
                    self.show_event('Готово.')
                elif result['code'] == 'conflict':
                    self.show_event('Настройки изменились в другом окне. Обновите данные и подтвердите действие заново.')
                else:
                    self.show_event(result.get('message') or result['code'])
            elif kind == 'diagnostic':
                self.query_one('#diagnostic-report', TextArea).load_text(result['report'])
                self.show_event('Диагностика завершена. Сетевой успех не подтверждает голос или обход через VPN.')
            elif kind == 'journal':
                self.query_one('#journal-report', TextArea).load_text(result['text'] + '\n' + result['warning'])
                self.show_event('Журнал обновлён.' if result['ok'] else 'Не удалось прочитать журнал.')
        except Exception as e:
            if kind == 'snapshot':
                self.snapshot = dict(self.snapshot, revision=None, service_state='unknown', autostart='unknown')
                self.query_one('#service', Static).update('Состояние недоступно')
                self.query_one('#service-action', Button).label = 'Запустить'
                self.query_one('#autostart', Static).update('Автозапуск: неизвестно')
                self.query_one('#autostart-action', Button).label = 'Включить автозапуск'
            self.show_event('Ошибка: ' + str(e))
        finally:
            self.pending = None
            self.controls()
            if self.closing:
                self.exit()
            elif kind == 'mutation':
                self.action_refresh()

    def apply_snapshot(self, snapshot, strategies):
        first = not self.snapshot
        recovered = bool(self.snapshot) and self.snapshot.get("revision") is None and snapshot.get("revision") is not None
        self.snapshot = snapshot
        self.strategy_names = list(strategies)
        config = snapshot.get('config') or {}
        state = snapshot.get('service_state', 'unknown')
        service = {'active': 'Сервис работает', 'inactive': 'Сервис остановлен', 'failed': 'Сбой сервиса'}.get(state, 'Состояние сервиса: ' + state)
        self.query_one('#service', Static).update(service)
        self.query_one('#service-action', Button).label = 'Остановить' if state == 'active' else 'Запустить'
        auto = snapshot.get('autostart', 'unknown')
        self.query_one('#autostart', Static).update('Автозапуск: ' + {'enabled': 'включён', 'disabled': 'выключен'}.get(auto, auto))
        self.query_one('#autostart-action', Button).label = 'Выключить автозапуск' if auto == 'enabled' else 'Включить автозапуск'
        self.query_one('#connection', Static).update(f"Интерфейс: {config.get('interface', '—')}\nСтратегия: {config.get('strategy', '—')}")
        self.query_one('#current-strategy', Static).update('Текущая стратегия: ' + config.get('strategy', '—'))
        self.profile_rows = {entry['name']: entry for entry in snapshot.get('profiles', [])}
        select = self.query_one('#profile-select', Select)
        previous = select.value
        select.set_options([(Text(name + (' · повреждён' if entry.get('config') is None else '')), name)
                            for name, entry in self.profile_rows.items()])
        if previous in self.profile_rows:
            select.value = previous
        self.filter_strategies()
        self.profile_detail()
        if snapshot.get('revision') is None:
            self.show_event('Настройки прочитаны не полностью: ' + (snapshot.get('revision_error') or 'изменения недоступны'))
        elif first or recovered:
            self.show_event('Настройки прочитаны.')

    def filter_strategies(self):
        text = self.query_one('#strategy-search', Input).value.casefold()
        select = self.query_one('#strategy-select', Select)
        previous = select.value
        choices = [name for name in self.strategy_names if text in name.casefold()]
        select.set_options([(Text(name), name) for name in choices])
        if previous in choices:
            select.value = previous

    def profile_detail(self):
        name = self.query_one('#profile-select', Select).value
        entry = self.profile_rows.get(name)
        config = entry.get('config') if entry else None
        text = (f"{name}\nСтратегия: {config['strategy']} · интерфейс: {config['interface']}" if config else
                (entry.get('error') or 'Профиль повреждён') if entry else 'Выберите профиль' if self.profile_rows else 'Пока нет профилей. Сохраните текущую настройку.')
        self.query_one('#profile-detail', Static).update(text)

    def on_select_changed(self, event):
        if event.select.id == 'profile-select':
            self.profile_detail()
        self.controls()

    def on_input_changed(self, event):
        if event.input.id == 'strategy-search':
            self.filter_strategies()
            self.controls()

    def mutate(self, action, value=None, revision=None):
        if action in core.REVISION_ACTIONS and self.snapshot.get('revision') is None:
            return
        self.schedule('mutation', lambda: self.backend.request(action, value, revision), auth=True)

    def save_name(self, name, revision, names):
        if name is None or self.closing:
            return
        if name in names:
            self.push_screen(Confirm(f'Заменить профиль «{name}» текущей настройкой?'),
                             lambda yes: self.mutate('profile-replace', name, revision) if yes else None)
        else:
            self.mutate('profile-save', name, revision)

    def on_button_pressed(self, event):
        name = event.button.id
        if name in ('copy-diagnostic', 'copy-journal'):
            area = '#diagnostic-report' if name == 'copy-diagnostic' else '#journal-report'
            self.copy_to_clipboard(self.query_one(area, TextArea).text)
            self.show_event('Текст отправлен в буфер терминала (если поддерживается).')
            return
        if self.pending is not None or self.closing:
            return
        revision = self.snapshot.get('revision')
        if name.startswith('profile-') or name == 'strategy-apply':
            if revision is None:
                return
        if name == 'service-action':
            self.mutate('stop' if self.snapshot.get('service_state') == 'active' else 'start')
        elif name == 'restart':
            self.mutate('restart')
        elif name == 'autostart-action':
            self.mutate('disable' if self.snapshot.get('autostart') == 'enabled' else 'enable')
        elif name == 'profile-save':
            names = set(self.profile_rows)
            self.push_screen(ProfileName(), lambda value: self.save_name(value, revision, names))
        elif name in ('profile-restore', 'profile-replace', 'profile-delete'):
            selected = self.query_one('#profile-select', Select).value
            if selected not in self.profile_rows:
                return
            if name == 'profile-restore':
                self.mutate(name, selected, revision)
            else:
                verb = 'Удалить' if name == 'profile-delete' else 'Заменить'
                self.push_screen(Confirm(f'{verb} профиль «{selected}»?'),
                                 lambda yes: self.mutate(name, selected, revision) if yes else None)
        elif name == 'strategy-apply':
            selected = self.query_one('#strategy-select', Select).value
            if selected is not Select.NULL:
                self.mutate('strategy', selected, revision)
        elif name == 'diagnose':
            privileged = self.query_one('#diagnostic-auth', Checkbox).value
            self.schedule('diagnostic', lambda: self.backend.diagnose(privileged=privileged), auth=privileged)
        elif name == 'journal-refresh':
            self.schedule('journal', self.backend.journal)

    def action_quit(self):
        if self.closing:
            return
        self.closing = True
        if self._poll:
            self._poll.stop()
        self.show_event('Завершаем текущую операцию…')
        self.controls()
        if self.pending is None:
            self.exit()
