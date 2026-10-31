import bpy
def use_gpu():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for t in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = t; prefs.get_devices()
            for d in prefs.devices: d.use = (d.type == t)
            if any(d.use for d in prefs.devices): break
        except Exception: pass
    for sc in bpy.data.scenes:
        sc.cycles.device = 'GPU'
    print("GPU:", prefs.compute_device_type, [d.name for d in prefs.devices if d.use], flush=True)
