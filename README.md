# 🎨 iRacing PSD → PNG Converter  

This tool is a fast, modern, and user‑friendly PSD‑to‑PNG converter designed specifically for **iRacing paint templates**. It allows creators to preview and export liveries with full control over layer visibility — all wrapped in a smooth PySide6 interface with cinematic UI touches.

Built for speed, accuracy, and ease of use.

---

## 🚀 Features

### ✔ Real‑Time Preview Rendering
- Automatically composites your PSD at **50% scale** for fast previews  
- Uses **4 CPU cores** via Python multiprocessing  
- Smooth fade‑in animation for every update  
- UI stays responsive even during heavy rendering

### ✔ Full‑Resolution PNG Export
- Exports the final composite at full size  
- Perfect for uploading to iRacing

### ✔ Layer Visibility Control
- Full PSD layer tree  
- Toggle visibility of any layer or group  
- Instantly see the result in the preview window

### ✔ Cinematic About Window
- Frameless overlay  
- Smooth fade‑in animation  
- Clean stacked‑logo presentation  
- Clickable link to the creator’s YouTube channel

### ✔ Splash Screen
- Custom splash logo on startup  
- Professional feel from the moment the app launches

### ✔ PyInstaller‑Ready
- Fully compatible with **single‑file EXE builds**  
- Includes multiprocessing fixes for Windows  
- Worker functions isolated for stable execution

---

## 📦 Requirements

Install dependencies with:

```bash
pip install PySide6 psd-tools Pillow
