# 制作 (Created by)：sirvffg冷月笙寒
# 网站 (Website)：https://lygalaxy.cn

import os
import sys
import subprocess
import shutil

def main():
    print("=" * 50)
    print(" CoLong Idea Studio - Launcher Builder")
    print("=" * 50)
    
    # 确保我们在项目根目录（或者相对于脚本能找到根目录）
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    main_py_path = os.path.join(project_root, "main.py")
    
    if not os.path.exists(main_py_path):
        print(f"❌ Error: Cannot find main.py at {main_py_path}")
        sys.exit(1)

    print(f"[*] Target file: {main_py_path}")
    print(f"[*] Platform: {sys.platform}")
    
    # 检查并安装 pyinstaller
    try:
        import PyInstaller
    except ImportError:
        print("[*] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"])

    # 准备构建参数
    build_dir = os.path.join(current_dir, "build")
    dist_dir = os.path.join(project_root, "release_launcher")
    
    # 清理旧的构建产物
    for d in [build_dir, dist_dir]:
        if os.path.exists(d):
            print(f"[*] Cleaning up old directory: {d}")
            shutil.rmtree(d, ignore_errors=True)
            
    # 根据系统决定生成的应用名称和图标
    app_name = "CoLongIdeaStudio_Launcher"
    icon_path = os.path.join(project_root, "colong.png")
    
    if sys.platform.startswith('darwin'):
        app_name = "CoLongIdeaStudio"

    # 生成版本信息文件
    version_info_path = os.path.join(current_dir, "version_info.txt")
    with open(version_info_path, "w", encoding="utf-8") as f:
        f.write("""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    # filevers and prodvers should be always a tuple with four items: (1, 0, 0, 0)
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    # Contains a bitmask that specifies the valid bits 'flags'
    mask=0x3f,
    # Contains a bitmask that specifies the Boolean attributes of the file.
    flags=0x0,
    # The operating system for which this file was designed.
    # 0x4 - NT and there is no need to change it.
    OS=0x4,
    # The general type of file.
    # 0x1 - the file is an application.
    fileType=0x1,
    # The function of the file.
    # 0x0 - the function is not defined for this fileType
    subtype=0x0,
    # Creation date and time stamp.
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', 'sirvffg冷月笙寒'),
        StringStruct('FileDescription', 'CoLong Idea Studio Launcher'),
        StringStruct('FileVersion', '1.0.0.0'),
        StringStruct('InternalName', 'CoLongIdeaStudio_Launcher'),
        StringStruct('LegalCopyright', 'Copyright (c) 2026 sirvffg冷月笙寒'),
        StringStruct('OriginalFilename', 'CoLongIdeaStudio_Launcher.exe'),
        StringStruct('ProductName', 'CoLong Idea Studio'),
        StringStruct('ProductVersion', '1.0.0.0')])
      ]), 
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",              # 无控制台黑窗口
        "--onedir",                # 使用单目录模式以大幅提升启动速度
        "--contents-directory", "launcher_bin", # 将所有依赖放到 launcher_bin/ 目录下，让外层只剩一个清爽的 exe
        f"--name={app_name}",
        f"--workpath={build_dir}",
        f"--distpath={project_root}", # 直接将最终的产物输出到项目根目录
        f"--specpath={current_dir}",
        # 排除不必要的模块以减小体积
        "--exclude-module=tkinter",
        "--exclude-module=unittest",
        "--exclude-module=email",
        "--exclude-module=html",
        "--exclude-module=http.server",
        "--exclude-module=xmlrpc",
        "--exclude-module=pydoc",
        "--exclude-module=doctest",
        "--exclude-module=distutils",
        "--exclude-module=pdb",
        "--exclude-module=torch",
        "--exclude-module=tensorflow",
        "--exclude-module=scipy",
        "--exclude-module=matplotlib",
        "--exclude-module=pandas",
        "--exclude-module=pytest",
        "--exclude-module=selenium",
        "--exclude-module=scrapy",
    ]
    
    if sys.platform.startswith('win'):
        cmd.append(f"--version-file={version_info_path}")
    
    if os.path.exists(icon_path):
        cmd.append(f"--icon={icon_path}")
        # Add data file for the application window icon
        separator = ";" if sys.platform.startswith('win') else ":"
        cmd.append(f"--add-data={icon_path}{separator}.")
        
    cmd.append(main_py_path)
    
    print("\n[*] Starting build process with PyInstaller...")
    print(" ".join(cmd))
    print("-" * 50)
    
    try:
        subprocess.check_call(cmd)
        print("\n" + "=" * 50)
        print("✅ Build Completed Successfully!")
        
        output_dir = os.path.join(project_root, app_name)
        
        # 此时生成的是一个文件夹，里面有一个干净的 exe 和一个 bin 依赖目录
        # 为了让用户在根目录直接点击，我们将文件夹内的东西移动到根目录
        if sys.platform.startswith('win'):
            exe_path = os.path.join(output_dir, f"{app_name}.exe")
            bin_path = os.path.join(output_dir, "launcher_bin")
            
            # 移动 exe 到项目根目录
            target_exe = os.path.join(project_root, f"{app_name}.exe")
            if os.path.exists(target_exe):
                os.remove(target_exe)
            shutil.move(exe_path, target_exe)
            
            # 移动 bin 依赖文件夹到项目根目录，名称改为 launcher_bin (不隐藏)
            target_bin = os.path.join(project_root, "launcher_bin")
            if os.path.exists(target_bin):
                shutil.rmtree(target_bin, ignore_errors=True)
            shutil.move(bin_path, target_bin)
            
            # 删除空的构建输出目录
            shutil.rmtree(output_dir, ignore_errors=True)
            
            print(f"🎉 Launcher is ready!\n   Main executable is located at:\n   {target_exe}")
            print(f"   (Dependencies are stored in the 'launcher_bin' folder)")
            
        elif sys.platform.startswith('darwin'):
            # macOS 下 PyInstaller 生成的是一个完整的 .app 包，它本身就是一个文件夹，不需要分离 bin
            # 但是由于我们用了 --onedir，它可能会生成一个裸露的 Unix 可执行文件和一个 .app
            # 通常用户只需要 .app
            app_bundle_path = os.path.join(project_root, f"{app_name}.app")
            # 如果存在旧的，先删除
            if os.path.exists(app_bundle_path):
                shutil.rmtree(app_bundle_path, ignore_errors=True)
                
            # PyInstaller 默认在 macOS --windowed 模式下会生成 .app 到 dist 根目录
            src_app = os.path.join(project_root, app_name, f"{app_name}.app")
            if not os.path.exists(src_app):
                # 兼容不同版本的 PyInstaller 输出路径
                src_app = os.path.join(project_root, f"{app_name}.app")
                
            if os.path.exists(src_app) and src_app != app_bundle_path:
                shutil.move(src_app, app_bundle_path)
            
            shutil.rmtree(output_dir, ignore_errors=True)
            print(f"🎉 Launcher is ready!\n   Main application is located at:\n   {app_bundle_path}")
            
        else:
            # Linux
            exe_path = os.path.join(output_dir, app_name)
            bin_path = os.path.join(output_dir, "launcher_bin")
            
            target_exe = os.path.join(project_root, app_name)
            if os.path.exists(target_exe):
                os.remove(target_exe)
            shutil.move(exe_path, target_exe)
            
            target_bin = os.path.join(project_root, "launcher_bin")
            if os.path.exists(target_bin):
                shutil.rmtree(target_bin, ignore_errors=True)
            shutil.move(bin_path, target_bin)
            
            shutil.rmtree(output_dir, ignore_errors=True)
            
            print(f"🎉 Launcher is ready!\n   Main executable is located at:\n   {target_exe}")
            print(f"   (Dependencies are stored in the 'launcher_bin' folder)")
            
        print("=" * 50)
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build failed with exit code {e.returncode}")
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
