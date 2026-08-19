# Offline Bili

一个只播放由应用下载并验证过的视频的 Windows 11 便携播放器。它不包含浏览器内核，不提供站内搜索或推荐，只接受明确粘贴的视频链接。

当前已打通 Bili23 元数据解析、扫码登录、批量分 P/画质选择、DASH 下载、FFmpeg MP4 封装、原始弹幕下载、受管文件校验、libmpv 播放和历史记录。产品术语见 [CONTEXT.md](./CONTEXT.md)，关键架构决定见 [docs/adr](./docs/adr)。

## 开发运行

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python scripts\fetch_libmpv.py
.venv\Scripts\python scripts\fetch_ffmpeg.py
.venv\Scripts\python -m offline_bili
```

应用运行数据默认写在项目或可执行程序所在目录的 `data/`、`library/`、`logs/` 和 `tools/` 中。

> `data/` 中会保存哔哩哔哩登录 Cookie。它是便携数据，能够随程序文件夹迁移，但未绑定 Windows 账号加密；不要分享、上传或打包自己使用过的 `data/` 目录。发行构建会强制清空包内的 `data/`、`library/` 和 `logs/`。

当前开发版可在右上角账号入口选择旧程序文件夹，临时迁移旧版登录信息，避免重复扫码。这个迁移入口不会进入正式发布版。

## 播放快捷键

- `Space`：播放/暂停
- `F`：进入或退出全屏；双击画面也可进入全屏
- `Esc`：退出全屏
- `D`：开启/关闭弹幕
- `S`：开启/关闭字幕
- `←` / `→`：后退/前进 5 秒

全屏时，移动鼠标或使用播放快捷键会显示顶部标题和底部控件；继续播放且无操作时会自动隐藏。

## 构建便携 ZIP

```powershell
.venv\Scripts\python scripts\build_portable.py
```
