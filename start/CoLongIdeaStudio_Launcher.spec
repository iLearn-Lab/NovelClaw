# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\Data\\Desktop\\CoLong\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\Data\\Desktop\\CoLong\\colong.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'email', 'html', 'http.server', 'xmlrpc', 'pydoc', 'doctest', 'distutils', 'pdb', 'torch', 'tensorflow', 'scipy', 'matplotlib', 'pandas', 'pytest', 'selenium', 'scrapy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CoLongIdeaStudio_Launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='D:\\Data\\Desktop\\CoLong\\start\\version_info.txt',
    icon=['D:\\Data\\Desktop\\CoLong\\colong.png'],
    contents_directory='launcher_bin',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CoLongIdeaStudio_Launcher',
)
