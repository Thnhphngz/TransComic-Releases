from pathlib import Path

LIGHT = {
    "background": "#F5F0EC", "panel": "#FFFCF9", "sidebar": "#EEE3DC",
    "ink": "#30231D", "muted": "#8A756A", "accent": "#9B552C",
    "accent_hover": "#B36A38", "border": "#E7D8CE", "field": "#F7F1ED",
}
DARK = {
    "background": "#1D1815", "panel": "#302721", "sidebar": "#251D19",
    "ink": "#F6EDE5", "muted": "#B8A79B", "accent": "#D88A4E",
    "accent_hover": "#E69C60", "border": "#554138", "field": "#3A2D27",
}


def colors(widget):
    parent = widget
    while parent is not None:
        if hasattr(parent, 'dark'): return DARK if parent.dark else LIGHT
        parent = parent.parentWidget()
    return DARK if widget.palette().window().color().lightness() < 100 else LIGHT


def stylesheet(dark: bool) -> str:
    c = DARK if dark else LIGHT
    assets = (Path(__file__).parent / "assets").as_posix()
    return f"""
    QWidget {{ background: {c['background']}; color: {c['ink']}; font-family: 'Segoe UI'; font-size: 13px; }}
    QLabel {{ background: transparent; }}
    QWidget#toolbarControls, QWidget#toolbarActions, QWidget#advancedPanel {{ background: transparent; }}
    QScrollArea#chipScroll, QScrollArea#chipScroll > QWidget > QWidget {{ background: transparent; border: 0; }}
    QLabel#title {{ font-size: 27px; font-weight: 700; color: {c['accent']}; }}
    QLabel#section {{ font-size: 17px; font-weight: 650; }}
    QLabel#muted {{ color: {c['muted']}; }}
    QFrame#card, QFrame#sidebar {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 15px; }}
    QFrame#sidebar {{ background: {c['sidebar']}; border: 0; border-radius: 0; }}
    QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:0.25 {c['field']},stop:1 {c['field']}); border: 1px solid {c['border']}; border-radius: 10px; padding: 9px 15px; font-weight: 600; }}
    QPushButton:checked {{ background: {c['accent']}; color: {'#30231D' if dark else '#FFFCF9'}; border-color: {c['accent']}; }}
    QSplitter::handle {{ background: {c['border']}; width: 5px; }}
    QSplitter::handle:hover {{ background: {c['accent']}; }}
    QWidget#documentPanel {{ background: {c['sidebar']}; }}
    QWidget#documentPanel[dropActive="true"] {{ border: 2px solid {c['accent']}; }}
    QListView {{ border: 0; background: {c['sidebar']}; outline: 0; }}
    QToolTip {{ background: {c['panel']}; color: {c['ink']}; border: 1px solid {c['accent']}; }}
    QPushButton:hover {{ border-color: {c['border']}; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['field']}); }}
    QPushButton:pressed {{ background: {c['border']}; border-color: {c['accent']}; padding-top: 10px; padding-bottom: 8px; }}
    QPushButton:focus {{ outline: 0; }}
    QPushButton[keyboardFocus="true"] {{ border-color: {c['accent']}; }}
    QPushButton[role="ghost"] {{ background: transparent; }}
    QPushButton:disabled {{ color: {c['muted']}; background: {c['field']}; }}
    QPushButton#languageChip:checked, QPushButton#languageChip:checked:hover, QPushButton#languageChip:checked:pressed, QPushButton#languageChip:checked:focus {{ background: {c['accent']}; color: {'#30231D' if dark else '#FFFCF9'}; border-color: {c['accent']}; }}
    QPushButton#languageChip:disabled, QPushButton#languageChip:checked:disabled {{ color: {c['muted']}; background: {c['field']}; border-color: {c['border']}; }}
    QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: {'#30231D' if dark else '#FFFCF9'}; }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton[glassRole="primary"] {{ color: {'#30231D' if dark else '#FFFCF9'}; }}
    QPushButton[glassRole="primary"]:disabled {{ color: {c['muted']}; }}
    QToolButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['field']}); border: 1px solid {c['border']}; border-radius: 7px; padding: 3px; color: {c['ink']}; }}
    QToolButton:hover {{ background: {c['field']}; }}
    QToolButton:pressed {{ background: {c['border']}; }}
    QToolButton:disabled {{ color: {c['muted']}; }}
    QPushButton#primary:pressed {{ background: {c['accent']}; border-color: {c['ink']}; }}
    QPushButton#danger {{ background: {'#59372E' if dark else '#F6E5DF'}; color: {'#FFD6C7' if dark else '#8E3426'}; border-color: {'#956254' if dark else '#C58B7A'}; }}
    QPushButton#danger:hover {{ background: {'#714237' if dark else '#F1D3C9'}; }}
    QPushButton#danger:disabled, QPushButton#primary:disabled {{ background: {c['field']}; color: {c['muted']}; border-color: {c['border']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {c['field']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 6px 9px; selection-background-color: {c['accent']}; selection-color: {'#30231D' if dark else '#FFFCF9'}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
    QComboBox {{ padding-right: 30px; min-height: 20px; combobox-popup: 0; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['field']}); }}
    QComboBox:hover {{ border-color: {c['border']}; }}
    QComboBox:focus {{ outline: 0; }}
    QComboBox[keyboardFocus="true"] {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: 0; }}
    QComboBox::down-arrow {{ image: url("{assets}/chevron.svg"); width: 16px; height: 16px; }}
    QComboBox QLineEdit, QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{ border: 0; border-radius: 0; background: transparent; padding: 0; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['ink']}; border: 1px solid {c['border']}; padding: 5px; selection-background-color: {c['accent']}; selection-color: white; outline: 0; }}
    QComboBox QAbstractItemView::item {{ padding: 5px 9px; min-height: 22px; border-radius: 4px; }}
    QAbstractItemView#glassPopup {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['panel']},stop:1 {c['field']}); border: 1px solid {c['border']}; border-radius: 10px; padding: 4px; outline: 0; }}
    QDialog {{ background: {c['panel']}; }}
    QDialogButtonBox QPushButton {{ min-width: 68px; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 28px; min-width: 55px; min-height: 20px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 25px; height: 17px; border: 0; border-left: 1px solid {c['border']}; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 25px; height: 17px; border: 0; border-left: 1px solid {c['border']}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{assets}/up.svg"); width: 12px; height: 12px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{assets}/down.svg"); width: 12px; height: 12px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: {c['border']}; }}
    QCheckBox::indicator, QTableView::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['border']}; background: {c['panel']}; }}
    QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{assets}/check.svg"); }}
    QScrollBar:vertical {{ background: {c['field']}; width: 12px; margin: 2px; border-radius: 5px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; border-radius: 5px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: {c['field']}; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {c['border']}; min-width: 30px; border-radius: 5px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 6px; }}
    QMenu::item {{ padding: 8px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['field']}; }}
    QPlainTextEdit#cellEditor {{ background: {c['panel']}; border: 0; padding: 0; border-radius: 0; }}
    QTableView {{ background: {c['panel']}; alternate-background-color: {c['field']}; border: 1px solid {c['border']}; border-radius: 12px; gridline-color: {c['border']}; selection-background-color: {c['field']}; }}
    QHeaderView::section {{ background: {c['field']}; color: {c['ink']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 6px; font-weight: 700; }}
    QHeaderView#rowHeader::section {{ padding: 0 4px; }}
    QProgressBar {{ background: {c['field']}; border: 0; border-radius: 6px; height: 10px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 6px; }}
    """
