"""One explicit binding per profile, with the few Qt 5/6 API differences here."""
from .runtime import selected_profile

LEGACY = selected_profile() == "legacy"
if LEGACY:
    from PySide2 import QtCore, QtGui, QtNetwork, QtWidgets
    QAction = QtWidgets.QAction
else:
    from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets
    QAction = QtGui.QAction


def __getattr__(name):
    # Re-export Qt's widget classes and core Signal/Slot without changing Qt's
    # enum or QObject types. There is no ImportError-based binding fallback.
    for module in (QtCore, QtGui, QtNetwork, QtWidgets):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


def exec_dialog(dialog):
    return dialog.exec_() if LEGACY else dialog.exec()


def exec_application(app):
    return app.exec_() if LEGACY else app.exec()


def configure_dpi():
    if LEGACY and QtWidgets.QApplication.instance() is None:
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
