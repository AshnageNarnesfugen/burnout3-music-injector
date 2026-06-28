"""The dark-theme Qt stylesheet for the app."""

STYLESHEET = """
QMainWindow{background:#0d0d0d}
QWidget{color:#e0e0e0;font-family:'JetBrains Mono','Fira Code','Cascadia Code',monospace;font-size:12px}
QTabWidget::pane{border:1px solid #222;background:#111;border-radius:4px}
QTabBar::tab{background:#1a1a1a;color:#888;padding:10px 20px;margin-right:2px;border:1px solid #222;border-bottom:none;border-top-left-radius:6px;border-top-right-radius:6px;font-weight:bold;letter-spacing:1px}
QTabBar::tab:selected{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ff4500,stop:1 #cc3700);color:#fff;border-color:#ff4500}
QTabBar::tab:hover:!selected{background:#252525;color:#ccc}
QPushButton{background:#1e1e1e;color:#ccc;border:1px solid #333;padding:8px 16px;border-radius:6px;font-weight:bold}
QPushButton:hover{background:#2a2a2a;border-color:#ff4500;color:#ff6a00}
QPushButton:pressed{background:#ff4500;color:#fff}
QPushButton#primaryBtn{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff4500,stop:1 #ff6a00);color:#fff;border:none;padding:12px 28px;font-size:13px}
QPushButton#primaryBtn:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff5500,stop:1 #ff7a10)}
QPushButton#primaryBtn:disabled{background:#333;color:#666}
QPushButton#dangerBtn{background:rgba(255,50,50,0.15);color:#ff5252;border:1px solid rgba(255,50,50,0.3)}
QTableWidget{background-color:#111;alternate-background-color:#151515;gridline-color:#1e1e1e;border:1px solid #222;border-radius:6px;selection-background-color:rgba(255,69,0,0.2);selection-color:#ff8c00}
QTableWidget::item{padding:6px 8px;border-bottom:1px solid #1a1a1a}
QHeaderView::section{background:#1a1a1a;color:#888;padding:8px 10px;border:none;border-bottom:2px solid #ff4500;font-weight:bold;font-size:10px;letter-spacing:1px}
QProgressBar{border:1px solid #333;border-radius:8px;background:#1a1a1a;text-align:center;color:#fff;font-weight:bold;min-height:24px}
QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff4500,stop:1 #ff8c00);border-radius:7px}
QTextEdit{background:#0a0a0a;border:1px solid #222;border-radius:6px;color:#aaa;font-size:11px;padding:8px}
QTreeWidget{background:#0e0e0e;border:1px solid #222;border-radius:6px;color:#ccc;font-size:11px}
QTreeWidget::item{padding:3px 0}
QTreeWidget::item:selected{background:rgba(255,69,0,0.2);color:#ff8c00}
QGroupBox{border:1px solid #222;border-radius:8px;margin-top:16px;padding-top:20px;font-weight:bold;color:#ff8c00}
QGroupBox::title{subcontrol-origin:margin;left:16px;padding:0 8px}
QLabel#headerLabel{font-size:22px;font-weight:800;color:#ff4500}
QLabel#subtitleLabel{font-size:11px;color:#555;letter-spacing:2px}
"""
