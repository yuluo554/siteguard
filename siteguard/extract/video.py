# -*- coding: utf-8 -*-
"""视频抽帧：关键帧提取 → 复用 M4 视觉通路（M6 缓冲周加分项，无需新模型）。

设计纪律（照 M3 pyvis_mod / M4 detector 可注入范式）：
- opencv-python 只进 pyproject optional 组 ``video``，import 期零硬依赖；缺依赖
  抛 ValueError 带安装提示（照 report.export 范式），CLI 捕获后打印说明降级
  exit 0 不崩溃；
- 无新模型：抽出的关键帧 JPG 直接走 M4 ``vision.collect_vision_cards``
  （detector/model 可注入，检出类别映射受控词表，缺依赖/坏图优雅降级）；
- 关键帧选择 ``select_keyframes`` 为纯函数（帧号均匀抽样、含首帧、升序去重），
  不依赖 cv2、可独立测试；``reader`` 可注入（reader(video_path) ->
  (total_frames, get_frame)，get_frame(idx) 返回 JPEG 字节）供测试注入，
  真实解码仅在 opencv 可用时发生；无真实检出不得伪造（fake 仅限测试注入并标注）。
"""

from pathlib import Path

INSTALL_HINT = ("视频抽帧需要可选依赖 opencv-python（pyproject video 组）："
                "py -m pip install opencv-python "
                "-i https://pypi.tuna.tsinghua.edu.cn/simple")


def _import_cv2():
    try:
        import cv2  # 延迟导入，禁止 import 期硬依赖
        return cv2
    except Exception as exc:
        raise ValueError("%s（导入失败：%s）" % (INSTALL_HINT, exc)) from exc


def select_keyframes(total_frames, max_frames=8):
    """帧号均匀抽样（纯函数）：总帧数 ≤ max_frames 全保留；否则等距取 max_frames
    个帧号（含首帧 0、升序去重、不越界）。total_frames ≤ 0 返回空表。"""
    total = int(total_frames)
    cap = max(1, int(max_frames))
    if total <= 0:
        return []
    if total <= cap:
        return list(range(total))
    step = total / float(cap)
    return sorted({min(int(i * step), total - 1) for i in range(cap)})


def extract_keyframes(video_path, out_dir, max_frames=8, reader=None):
    """视频 → 关键帧 JPG 文件列表（keyframe_0001.jpg 起，写入 out_dir 并返回）。

    reader 注入仅供测试（fake 须标注）；缺省走 opencv 真实解码。缺依赖 / 打不开 /
    无有效帧 / 读帧失败一律 ValueError（CLI 捕获后打印说明降级，不崩溃）。
    """
    if reader is not None:
        total, get_frame = reader(str(video_path))
        frames = [(i, get_frame(i)) for i in select_keyframes(total, max_frames)]
    else:
        cv2 = _import_cv2()
        cap = cv2.VideoCapture(str(video_path))
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            frames = []
            for i in select_keyframes(total, max_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
                ok, frame = cap.read()
                if not ok:
                    raise ValueError("读取第 %d 帧失败" % i)
                ok2, buf = cv2.imencode(".jpg", frame)
                if not ok2:
                    raise ValueError("第 %d 帧编码 JPEG 失败" % i)
                frames.append((i, bytes(buf)))
        finally:
            cap.release()
    if not frames:
        raise ValueError("视频无有效帧（文件损坏或格式不支持）：%s"
                         % Path(video_path).name)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for n, (_, data) in enumerate(frames, 1):
        fp = out / ("keyframe_%04d.jpg" % n)
        fp.write_bytes(data)
        paths.append(fp)
    return paths


def collect_video_cards(video_path, out_dir, max_frames=8,
                        schema=None, detector=None, model=None, reader=None):
    """抽帧 → M4 视觉通路逐帧检测，返回 (cards, warnings)。

    detector/model 注入语义与 vision.collect_vision_cards 一致（测试注入须标注）；
    缺 opencv（且未注入 reader）时 ValueError 上抛，由调用方降级。
    """
    frames = extract_keyframes(video_path, out_dir, max_frames, reader=reader)
    from . import vision
    return vision.collect_vision_cards([str(p) for p in frames], schema=schema,
                                       detector=detector, model=model)
