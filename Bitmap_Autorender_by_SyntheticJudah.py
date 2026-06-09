bl_info = {
    "name": "Bitmap Autorender by SyntheticJudah",
    "author": "SJ",
    "version": (5, 2),
    "blender": (4, 5, 4),
    "location": "View3D > Sidebar > BitMap Autorender",
    "description": "Real-time auto-render of the scene to a 128×64 1-bit monochrome BMP preview, with Performance/Responsive modes, FPS limiting and optional disk export — for previewing scenes on small displays. GitHub: https://github.com/SyntheticJudah/Bitmap-Autorender-for-Blender",
    "category": "3D View"
}

import bpy
import time
from collections import deque
import os
import numpy as np
from PIL import Image
import hashlib

# Logging
def log(msg, level="INFO"):
    if level == "ERROR" or (getattr(bpy.context.scene, "BMP_settings", None) and bpy.context.scene.BMP_settings.debug):
        print(f"[BMP {time.strftime('%H:%M:%S')}] {msg}")

# Save 1-bit BMP
def save_1bit_bmp(pixels, filepath, frame_number=None):
    start_time = time.time()
    try:
        settings = bpy.context.scene.BMP_settings
        full_path = bpy.path.abspath(filepath)
        base_dir = os.path.dirname(full_path)
        name, ext = os.path.splitext(os.path.basename(full_path))
        if not ext:
            ext = ".bmp"
        final_name = f"{name}_{frame_number:04d}{ext}" if frame_number is not None else f"{name}{ext}"
        final_path = os.path.join(base_dir, final_name)
        if os.path.exists(final_path) and not settings.overwrite_file:
            return False
        os.makedirs(base_dir, exist_ok=True)
        arr = np.array(pixels, dtype=np.float32).reshape((64, 128, 4))
        gray = arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114
        bw = (gray > 0.5).astype(np.uint8) * 255
        img = Image.fromarray(bw, mode='L').convert('1')
        img.save(final_path, format='BMP')
        log(f"Saved BMP ({(time.time()-start_time)*1000:.2f}ms): {final_path}")
        return True
    except Exception as e:
        log(f"Error saving BMP: {e}", "ERROR")
        return False

# Load pixels
def get_pixels_from_image(filepath):
    try:
        img = Image.open(filepath).resize((128,64), Image.Resampling.LANCZOS).convert('RGBA')
        pixels = np.array(img, dtype=np.float32).ravel() / 255.0
        if len(pixels) != 128*64*4:
            log(f"Invalid pixel size: {len(pixels)}", "ERROR")
            return None
        return pixels.tolist()
    except Exception as e:
        log(f"Error loading pixels from {filepath}: {e}", "ERROR")
        return None

# Settings
class BMPSettings(bpy.types.PropertyGroup):
    save_output: bpy.props.BoolProperty(name="Save to Disk", default=True)
    overwrite_file: bpy.props.BoolProperty(name="Overwrite File", default=True)
    output_path: bpy.props.StringProperty(name="Output Path", default="//render/BMP_preview.bmp", subtype='FILE_PATH')
    max_queue_size: bpy.props.IntProperty(name="Max Queue", default=1, min=1, max=5)
    target_fps: bpy.props.IntProperty(name="Target FPS", default=15, min=5, max=120)
    skip_frames: bpy.props.IntProperty(name="Skip Frames", default=1, min=0, max=5)
    use_eevee_next: bpy.props.BoolProperty(name="Use Eevee Next (Experimental)", default=True)
    debug: bpy.props.BoolProperty(name="Debug Logging", default=True)
    render_mode: bpy.props.EnumProperty(
        name="Render Mode",
        description="Switch between Performance (optimized) and Responsive (render all changes)",
        items=[('PERFORMANCE', "Performance", "Render only on significant changes"),
               ('RESPONSIVE', "Responsive", "Render on every change")],
        default='PERFORMANCE'
    )

# State
_render_queue = deque()
_is_rendering = False
_running = False
_animation_playing = False
_last_interactive_time = 0
_manual_render_active = False
_preview_image = None
_fps_counter = 0
_current_fps = 0
_last_fps_time = 0
_last_frame_rendered = -1
_original_render_settings = {}
_original_world = {}
_original_viewport_settings = {}
_last_scene_signature = None

# Preview
def init_preview():
    global _preview_image
    if "BMP_Preview" not in bpy.data.images:
        _preview_image = bpy.data.images.new("BMP_Preview", 128, 64)
    else:
        _preview_image = bpy.data.images["BMP_Preview"]
    try:
        _preview_image.scale(128,64)
    except Exception:
        pass
    _preview_image.pixels[:] = [0.0]*(128*64*4)
    log("Preview initialized")

# Compute lightweight signature
def compute_scene_signature(scene):
    m = hashlib.sha256()
    cam = scene.camera
    if cam:
        try:
            m.update(cam.name.encode('utf-8'))
            m.update(str(tuple(round(x,6) for x in cam.matrix_world.translation)).encode('utf-8'))
            m.update(str(tuple(round(x,6) for x in cam.matrix_world.to_quaternion())).encode('utf-8'))
        except Exception:
            pass
    if scene.world:
        try:
            m.update(str(tuple(round(x,6) for x in scene.world.color)).encode('utf-8'))
            m.update(str(int(scene.world.use_nodes)).encode('utf-8'))
        except Exception:
            pass
    active_view_layer = getattr(bpy.context, "view_layer", None) or (scene.view_layers[0] if scene.view_layers else None)
    for obj in scene.objects:
        try:
            if obj.type != 'MESH':
                continue
            is_visible = (obj.name in active_view_layer.objects and not obj.hide_viewport) if active_view_layer else not obj.hide_get()
            if not is_visible:
                continue
            pos = tuple(round(v,6) for v in obj.matrix_world.translation)
            rot = tuple(round(v,6) for v in obj.matrix_world.to_quaternion())
            scale = tuple(round(v,6) for v in obj.matrix_world.to_scale())

            m.update(obj.name.encode('utf-8'))
            m.update(str(pos).encode('utf-8'))
            m.update(str(rot).encode('utf-8'))
            m.update(str(scale).encode('utf-8'))

            # Geometry Nodes signature
            for mod in obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    try:
                        m.update(mod.node_group.name.encode('utf-8'))
                        m.update(str(len(mod.node_group.nodes)).encode('utf-8'))
                        m.update(str(len(mod.node_group.links)).encode('utf-8'))
                    except Exception:
                        pass
            
            for slot in getattr(obj, "material_slots", []):
                if slot.material:
                    m.update(slot.material.name.encode('utf-8'))
        except Exception:
            continue
    return m.hexdigest()

# Depsgraph significant updates
def depsgraph_has_significant_updates(depsgraph):
    try:
        for update in getattr(depsgraph, "updates", []):
            uid = getattr(update, "id", None)

            # Object-level changes
            if isinstance(uid, bpy.types.Object):
                if (
                    getattr(update, "is_updated_transform", False)
                    or getattr(update, "is_updated_geometry", False)
                    or getattr(update, "is_updated_shading", False)
                ):
                    return True

            # Geometry Nodes trees (MAIN CASE)
            if isinstance(uid, bpy.types.GeometryNodeTree):
                return True

            # Generic node trees (safety net)
            if isinstance(uid, bpy.types.NodeTree):
                return True

            # Modifier updates (GN modifiers)
            if isinstance(uid, bpy.types.Modifier):
                if uid.type == 'NODES':
                    return True

            # Materials / world / camera / light
            if isinstance(uid, (bpy.types.Material, bpy.types.World, bpy.types.Camera, bpy.types.Light)):
                return True

    except Exception:
        return True

    return False

# Render frame
def render_next_frame():
    global _is_rendering, _render_queue, _preview_image, _fps_counter, _current_fps, _last_fps_time, _last_frame_rendered
    if not _render_queue:
        _is_rendering = False
        return None
    frame_start = time.time()
    task = _render_queue.popleft()
    scene = bpy.context.scene
    settings = scene.BMP_settings
    if task['type'] == 'animation' and abs(task['frame'] - _last_frame_rendered) < settings.skip_frames:
        return 0.01
    try:
        log(f"Starting render for frame {task['frame']} (queue left: {len(_render_queue)})")
        if not scene.camera:
            log("No active camera!", "ERROR")
            _is_rendering = False
            return None
        scene.frame_set(task['frame'])
        blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
        temp_filepath = os.path.join(blend_dir, "temp_BMP_render.bmp")
        scene.render.filepath = temp_filepath
        scene.render.image_settings.file_format = 'BMP'

        # Force viewport redraw
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        bpy.ops.render.render(write_still=True)
        render = bpy.data.images.get("Render Result")
        pixels = None
        if render and tuple(render.size) == (128,64):
            pixels = list(render.pixels)
        elif os.path.exists(temp_filepath):
            pixels = get_pixels_from_image(temp_filepath)

        if not pixels or len(pixels) != 128*64*4:
            log(f"Invalid pixel data: {len(pixels) if pixels else 'None'}", "ERROR")
            _is_rendering = False
            return None

        if _preview_image:
            _preview_image.pixels[:] = pixels
            try:
                _preview_image.update()
            except Exception:
                pass

        if settings.save_output:
            frame_num = task['frame'] - scene.frame_start + 1 if task['type'] == 'animation' else None
            save_1bit_bmp(pixels, settings.output_path, frame_num)

        _last_frame_rendered = task['frame']

        # FPS tracking
        _fps_counter += 1
        now = time.time()
        if now - _last_fps_time >= 1.0:
            _current_fps = round(_fps_counter / (now - _last_fps_time), 1) if (now - _last_fps_time) > 0 else 0
            _fps_counter = 0
            _last_fps_time = now
            update_panel()

        try:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
        except Exception:
            pass

        return max(0.02, 1.0 / settings.target_fps)
    except Exception as e:
        log(f"Render error: {e}", "ERROR")
        _is_rendering = False
        return None

# Handlers
def on_render_pre(scene):
    global _manual_render_active
    _manual_render_active = True

def on_render_post(scene):
    global _manual_render_active
    _manual_render_active = False

def scene_changed(depsgraph):
    global _last_interactive_time, _last_scene_signature
    if not _running:
        return
    screen = bpy.context.screen
    is_playing = getattr(screen, "is_animation_playing", False) if screen else False
    if is_playing or _manual_render_active:
        return
    now = time.time()
    if now - _last_interactive_time < 0.08:
        return
    scene = bpy.context.scene
    settings = scene.BMP_settings
    significant = depsgraph_has_significant_updates(depsgraph)
    try:
        sig = compute_scene_signature(scene)
    except Exception:
        sig = None
    if settings.render_mode == 'PERFORMANCE' and not significant and sig == _last_scene_signature:
        _last_interactive_time = now
        return
    _last_scene_signature = sig
    _last_interactive_time = now
    current_frame = scene.frame_current
    if not _render_queue or _render_queue[-1]['frame'] != current_frame:
        _render_queue.append({'frame': current_frame, 'time': now, 'type': 'interactive'})
        trim_queue()
        start_render_loop()

def frame_change_handler(scene):
    global _animation_playing, _render_queue, _last_frame_rendered
    if not _running:
        return
    screen = bpy.context.screen
    is_playing = getattr(screen, "is_animation_playing", False) if screen else False
    if is_playing and not _animation_playing:
        _animation_playing = True
    elif not is_playing and _animation_playing:
        _animation_playing = False
        _render_queue = deque([t for t in _render_queue if t['type'] != 'animation'])
    settings = scene.BMP_settings
    current_frame = scene.frame_current
    if settings.render_mode == 'RESPONSIVE' or abs(current_frame - _last_frame_rendered) >= settings.skip_frames:
        _render_queue.append({'frame': current_frame, 'time': time.time(), 'type': 'animation'})
        trim_queue()
        start_render_loop()

def trim_queue():
    max_size = bpy.context.scene.BMP_settings.max_queue_size
    while len(_render_queue) > max_size:
        _render_queue.popleft()

def start_render_loop():
    global _is_rendering
    if _is_rendering or not _render_queue:
        return
    _is_rendering = True
    bpy.app.timers.register(render_next_frame, first_interval=0.01)

def update_panel():
    try:
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
                break
    except Exception:
        pass

def ui_update_timer():
    return 0.5 if _running else None

# UI Panel
class BMP_PT_panel(bpy.types.Panel):
    bl_label = "BMP Autorended by SJ"
    bl_idname = "BMP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BMP Autorended by SJ"
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.BMP_settings
        col = layout.column(align=True)
        col.label(text=f"Status: {'RUNNING' if _running else 'STOPPED'}", icon='PLAY' if _running else 'PAUSE')
        row = col.row(align=True)
        row.operator("bmp.start" if not _running else "bmp.stop", text="START" if not _running else "STOP", icon='PLAY' if not _running else 'PAUSE')
        col.prop(settings, "render_mode")
        col.prop(settings, "save_output")
        if settings.save_output:
            col.prop(settings, "overwrite_file")
            col.prop(settings, "output_path", text="")
        col.prop(settings, "max_queue_size")
        col.prop(settings, "target_fps")
        col.prop(settings, "skip_frames")
        col.prop(settings, "use_eevee_next")
        col.prop(settings, "debug")
        col.label(text=f"FPS: {_current_fps}")
        col.label(text=f"Queue: {len(_render_queue)}")

# Operators
class BMP_OT_start(bpy.types.Operator):
    bl_idname = "bmp.start"
    bl_label = "Start"
    def execute(self, context):
        global _running, _last_fps_time, _fps_counter, _current_fps, _original_render_settings, _original_world, _animation_playing, _original_viewport_settings, _last_scene_signature
        if _running:
            return {'FINISHED'}
        init_preview()
        scene = context.scene
        settings = scene.BMP_settings
        if settings.save_output:
            output_path = bpy.path.abspath(settings.output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Store original settings
        _original_render_settings = {
            'resolution_x': scene.render.resolution_x,
            'resolution_y': scene.render.resolution_y,
            'engine': scene.render.engine,
            'file_format': scene.render.image_settings.file_format,
            'taa_samples': getattr(scene.eevee, "taa_render_samples", 1),
            'filepath': scene.render.filepath,
        }
        _original_viewport_settings = {}
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                if space:
                    _original_viewport_settings['shading'] = {
                        'type': getattr(space.shading, 'type', 'SOLID'),
                        'light': getattr(space.shading, 'light', 'STUDIO'),
                        'show_shadows': getattr(space.shading, 'show_shadows', False),
                        'show_cavity': getattr(space.shading, 'show_cavity', False),
                        'show_specular_highlight': getattr(space.shading, 'show_specular_highlight', False),
                        'color_type': getattr(space.shading, 'color_type', 'MATERIAL'),
                    }
                break
        if scene.world:
            _original_world = {'use_nodes': scene.world.use_nodes, 'color': scene.world.color}
        # Apply BMP settings
        scene.render.resolution_x = 128
        scene.render.resolution_y = 64
        scene.render.engine = 'BLENDER_EEVEE_NEXT' if settings.use_eevee_next else 'BLENDER_EEVEE'
        scene.render.image_settings.file_format = 'BMP'
        try:
            scene.eevee.taa_render_samples = 1
        except Exception:
            pass
        scene.render.use_compositing = True
        scene.render.use_sequencer = False
        try:
            scene.render.use_simplify = True
            scene.render.simplify_subdivision = 0
            scene.render.simplify_child_particles = 0
        except Exception:
            pass
        world = scene.world or bpy.data.worlds.new("BMP_World")
        scene.world = world
        try:
            world.use_nodes = False
        except Exception:
            pass
        world.color = (0.0, 0.0, 0.0)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                if space:
                    space.shading.type = 'RENDERED'
                    try:
                        space.shading.light = 'FLAT'
                        space.shading.show_shadows = False
                        space.shading.show_cavity = False
                        space.shading.show_specular_highlight = False
                        space.shading.color_type = 'MATERIAL'
                    except Exception:
                        pass
        _running = True
        _animation_playing = False
        _last_fps_time = time.time()
        _fps_counter = 0
        _current_fps = 0
        _last_scene_signature = compute_scene_signature(scene) if scene else None
        # Register handlers
        for handler, lst in ((scene_changed, bpy.app.handlers.depsgraph_update_post),
                             (frame_change_handler, bpy.app.handlers.frame_change_post),
                             (on_render_pre, bpy.app.handlers.render_pre),
                             (on_render_post, bpy.app.handlers.render_post)):
            if handler not in lst:
                lst.append(handler)
        bpy.app.timers.register(ui_update_timer, first_interval=0.5)
        return {'FINISHED'}

class BMP_OT_stop(bpy.types.Operator):
    bl_idname = "bmp.stop"
    bl_label = "Stop"
    def execute(self, context):
        global _running, _is_rendering, _animation_playing, _render_queue, _current_fps
        for handler_list in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.frame_change_post, bpy.app.handlers.render_pre, bpy.app.handlers.render_post):
            for handler in list(handler_list):
                if handler in (scene_changed, frame_change_handler, on_render_pre, on_render_post):
                    handler_list.remove(handler)
        scene = context.scene
        # Restore render settings
        if _original_render_settings:
            scene.render.resolution_x = _original_render_settings.get('resolution_x', scene.render.resolution_x)
            scene.render.resolution_y = _original_render_settings.get('resolution_y', scene.render.resolution_y)
            scene.render.engine = _original_render_settings.get('engine', scene.render.engine)
            scene.render.image_settings.file_format = _original_render_settings.get('file_format', scene.render.image_settings.file_format)
            scene.render.filepath = _original_render_settings.get('filepath', scene.render.filepath)
            try:
                scene.eevee.taa_render_samples = _original_render_settings.get('taa_samples', getattr(scene.eevee, 'taa_render_samples', 1))
            except Exception:
                pass
        # Restore viewport
        if _original_viewport_settings:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    space = area.spaces.active
                    if space and 'shading' in _original_viewport_settings:
                        s = _original_viewport_settings['shading']
                        space.shading.type = s.get('type', space.shading.type)
                        space.shading.light = s.get('light', getattr(space.shading, 'light', None))
                        space.shading.show_shadows = s.get('show_shadows', getattr(space.shading, 'show_shadows', False))
                        space.shading.show_cavity = s.get('show_cavity', getattr(space.shading, 'show_cavity', False))
                        space.shading.show_specular_highlight = s.get('show_specular_highlight', getattr(space.shading, 'show_specular_highlight', False))
                        try:
                            space.shading.color_type = s.get('color_type', getattr(space.shading, 'color_type', 'MATERIAL'))
                        except Exception:
                            pass
                    break
        # Restore world
        if _original_world and scene.world:
            world = scene.world
            world.use_nodes = _original_world.get('use_nodes', world.use_nodes)
            if not world.use_nodes:
                world.color = _original_world.get('color', world.color)
        _running = False
        _is_rendering = False
        _animation_playing = False
        _render_queue.clear()
        _current_fps = 0
        return {'FINISHED'}

# Registration
classes = (BMPSettings, BMP_PT_panel, BMP_OT_start, BMP_OT_stop)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.BMP_settings = bpy.props.PointerProperty(type=BMPSettings)

def unregister():
    if _running:
        try:
            bpy.ops.bmp.stop()
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "BMP_settings"):
        del bpy.types.Scene.BMP_settings

if __name__ == "__main__":
    register()
