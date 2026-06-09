# Bitmap Autorender for Blender by SyntheticJudah

A Blender add-on that renders the active scene in real time into a tiny **128×64 black‑and‑white image** and saves it as a **1‑bit BMP**. In effect, it's a live preview of how the scene would look on a small monochrome display.

<img width="750" height="390" alt="demo" src="https://github.com/user-attachments/assets/376dfe16-b5c5-437c-b3db-396f90d2ed52" />

# Interface

<img width="1987" height="580" alt="image" src="https://github.com/user-attachments/assets/2e74618c-2fbd-4dd3-9159-e3ce0e3c10f4" />

## !!! Disclaimer !!!

I wrote and used this script while creating screensavers for our new OLED screens for Elektron Machinedrum / Monomachine / Cctatrack MKI as part of my work at [**MachineStore**](https://discord.gg/yxg75JCsh3). Keep in mind that this is not a polished software product, but rather a rough-around-the-edges tool designed to solve a specific problem. You may still encounter some crashes, but they are rare enough that you can work comfortably. Just remember to save your work frequently.

## Requirements

- Blender 4.5+
- [Pillow](https://python-pillow.org/) (PIL) installed in Blender's Python - the add-on uses it to convert and write the 1‑bit BMP.
- NumPy (already bundled with Blender).
- A properly configured render and scene (an example *.blend file is also included)

## Usage

1. Install and enable the add-on, then open the **BMP** tab in the 3D Viewport sidebar (`N`).
2. Press **START**. The add-on switches the scene into preview mode and begins rendering automatically as you work.
3. Press **STOP** to end. All original render, world and viewport settings are restored.

The result is shown live in the `BMP_Preview` image datablock and, when saving is enabled, written to disk (default `//render/BMP_preview.bmp`).

## How it works

- Scene changes are tracked through the `depsgraph_update_post` and `frame_change_post` handlers.
- Frames are pushed onto a small queue and rendered under an FPS cap.
- During animation playback, saved files are numbered per frame.

## How the image is generated

1. The scene is rendered at 128×64.
2. Pixels are converted to grayscale using the standard luminance weights (0.299 / 0.587 / 0.114).
3. The result is thresholded at 0.5.
4. It is converted into a strictly black‑and‑white mode `1` image.
5. The image is saved in BMP format.

## Operating modes

- **Performance** - renders only on significant changes. It filters depsgraph updates and compares a SHA‑256 signature of the scene (camera, world, transforms of visible meshes, geometry nodes, and materials), skipping renders when nothing meaningful has changed.
- **Responsive** - renders on every change.

## Performance controls

- **Target FPS** - 5–120 (it also depends on the upper threshold set in the scene.)
- **Skip frames** - drop intermediate animation frames.
- **Max queue size** - 1–5.
- Interactive updates are throttled (~0.08 s) to avoid render floods.

## Render settings (temporary)

On **START**, the add-on saves your current settings and switches the scene to:

- Eevee / Eevee Next, 128×64 resolution, 1 TAA sample.
- A black, node‑less world.
- FLAT viewport shading in RENDERED mode.
- Simplify enabled.

On **STOP**, all of these are restored cleanly.

## Interface

A panel in the 3D Viewport sidebar (**BMP** tab) showing the current status, a **START / STOP** button, output settings, and a live FPS and queue‑length readout.

## Demo file

`Bitmap_Autorender.blend` (saved with Blender 4.5.4) is a ready-made scene for trying out the add-on. It contains a small tent built with a Geometry Nodes modifier, a cube, a ground plane, a single bright Area light, and a perspective camera (58 mm).

### How the scene is rendered

- **Engine:** Eevee Next.
- **Resolution:** 128×64 at 100% scale, output as BMP.
- **World:** a flat black background (nodes disabled), so the subject reads as bright shapes against pure black.
- **Lighting:** a single Area light with a very high power value, which keeps the tiny frame cleanly exposed.
- **Camera:** standard perspective projection.

These are the same parameters the add-on enforces while running, so the demo behaves consistently whether you render it manually or through **START**.

### Compositing setup

The distinctive monochrome look is produced in the **compositor** (node-based compositing is enabled). Because the add-on renders with compositing turned on, every preview frame passes through this node tree. The chain combines edge detection, hard thresholding and a touch of optical distortion and noise:

- **Render Layers** feeds the rendered image into the tree.
- **RGB to BW** flattens it to grayscale.
- A **Color Ramp** with two stops and *Constant* interpolation acts as a hard black/white threshold - this is what gives the crisp 1-bit feel rather than smooth gradients.
- Two **Filter** nodes (*Prewitt* and *Sobel*) perform edge detection for outlined / stylized shapes.
- A **Lens Distortion** node adds a subtle optical/CRT-style warp.
- A **Noise Texture** mixed in (via a **Mix** node) introduces texture/dithering.
- **Set Alpha** and the final **Composite** node output the result.

You can tune the look by adjusting the Color Ramp stops (threshold position), swapping or disabling the edge filters, or reducing the noise/lens distortion to taste.
