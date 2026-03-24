from pathlib import Path
import io
from psd_tools import PSDImage
from psd_tools.api.layers import Group
from PIL import Image

def render_preview_worker(psd_path_str, visibility_state, scale):
    psd_path = Path(psd_path_str)
    psd = PSDImage.open(psd_path)

    vis_map = {path: vis for path, vis in visibility_state}

    def apply_visibility(layers, parent_path):
        for idx, layer in enumerate(layers):
            path = parent_path + (idx,)
            if path in vis_map:
                layer.visible = vis_map[path]
            if isinstance(layer, Group):
                apply_visibility(layer, path)

    apply_visibility(psd, ())

    composite = psd.composite()
    if scale != 1.0:
        w, h = composite.size
        composite = composite.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    composite.save(buf, format="PNG")
    return buf.getvalue()
