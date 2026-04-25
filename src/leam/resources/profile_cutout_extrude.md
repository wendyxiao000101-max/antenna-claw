# Profile, Polygon & Cutout Extrude Reference

This reference covers how to build solids whose cross-section cannot be represented
by a CST built-in 3D primitive (Brick/Cylinder/etc.).  Use these patterns whenever
the JSON solid description contains:
- `"primitive": "polygon"` or `"profile"` or `"cutout"`
- An explicit `profile_definition` list of [x, y] point pairs
- Shape keywords such as "tapered slot", "Vivaldi", "extrude", or "spline"
- `Role` containing "Cutout"

---

## Pattern 1 — Extrude from Explicit Pointlist (polygon primitive)

Use when `profile_definition` supplies an explicit list of [x, y] vertices.
The polygon is defined on the XY plane and extruded along Z.

```vba
With Extrude
     .Reset
     .Name "SlotBody"
     .Component "component1"
     .Material "Vacuum"
     .Mode "Pointlist"
     .Height "t_sub"
     .Twist "0.0"
     .Taper "0.0"
     .Origin "0.0", "0.0", "0.0"
     .Uvector "1.0", "0.0", "0.0"
     .Vvector "0.0", "1.0", "0.0"
     .Point  "x0", "y0"
     .LineTo "x1", "y1"
     .LineTo "x2", "y2"
     .LineTo "x3", "y3"
     .LineTo "x0", "y0"
     .Create
End With
```

**Rules:**
- First vertex uses `.Point`, all subsequent vertices (including close-back) use `.LineTo`.
- Always close the polygon by repeating the first vertex as the final `.LineTo`.
- For a cutout body set `.Material "Vacuum"`.  The body will be Boolean-subtracted later.

---

## Pattern 2 — Spline Profile + ExtrudeCurve (smooth curved outline)

Use when the profile has smooth/curved edges (spline, arc) rather than straight lines.
First define a named closed curve, then extrude it.

```vba
' Step 1: define the closed spline profile on the XY plane
With Spline
     .Reset
     .Name "vivaldi_profile"
     .Curve "curve_slot"
     .Point "-W_feed/2", "0"
     .SetInterpolationType "PointInterpolation"
     .LineTo "-W_open/2", "L_slot"
     .LineTo  "W_open/2", "L_slot"
     .LineTo  "W_feed/2", "0"
     .LineTo "-W_feed/2", "0"
     .Create
End With

' Step 2: extrude the closed curve into a solid
With ExtrudeCurve
     .Reset
     .Name "TaperedSlotCutout"
     .Component "component1"
     .Material "Vacuum"
     .Thickness "t_cu"
     .Twistangle "0.0"
     .Taperangle "0.0"
     .DeleteProfile "True"
     .Curve "curve_slot:vivaldi_profile"
     .Create
End With
```

---

## Pattern 3 — Vivaldi Tapered Slot (exponential taper via Pointlist)

Use for any Vivaldi / LTSA / tapered-slot antenna where the slot aperture widens
exponentially from a narrow feed gap (`W_feed`) to a wide aperture (`W_open`) over
length `L_slot`.

The multipliers below assume `W_open / W_feed ≈ 20`.  If the ratio differs,
scale the intermediate multipliers accordingly:
  multiplier at step k/N = (W_open/W_feed)^(k/N) / 2

```vba
' Required parameters (define in XXX_para.bas or reuse if already declared):
' W_feed  — slot width at feed end (mm)
' W_open  — slot aperture width (mm)
' L_slot  — slot length along propagation direction (mm)
' t_cu    — conductor thickness (mm)
' Z_cu    — z-coordinate of the copper layer bottom face

With Extrude
     .Reset
     .Name "TaperedSlotCutout"
     .Component "component1"
     .Material "Vacuum"
     .Mode "Pointlist"
     .Height "t_cu"
     .Twist "0.0"
     .Taper "0.0"
     .Origin "0.0", "0.0", "Z_cu"
     .Uvector "1.0", "0.0", "0.0"
     .Vvector "0.0", "1.0", "0.0"
     ' ---- right edge: feed gap → aperture (exponential, 8 segments) ----
     .Point   "W_feed/2",      "0"
     .LineTo  "W_feed*0.780",  "L_slot/7"
     .LineTo  "W_feed*1.215",  "L_slot*2/7"
     .LineTo  "W_feed*1.890",  "L_slot*3/7"
     .LineTo  "W_feed*2.950",  "L_slot*4/7"
     .LineTo  "W_feed*4.595",  "L_slot*5/7"
     .LineTo  "W_feed*7.150",  "L_slot*6/7"
     .LineTo  "W_open/2",      "L_slot"
     ' ---- aperture edge (straight) ----
     .LineTo  "-W_open/2",     "L_slot"
     ' ---- left edge: aperture → feed gap (mirror of right) ----
     .LineTo  "-W_feed*7.150", "L_slot*6/7"
     .LineTo  "-W_feed*4.595", "L_slot*5/7"
     .LineTo  "-W_feed*2.950", "L_slot*4/7"
     .LineTo  "-W_feed*1.890", "L_slot*3/7"
     .LineTo  "-W_feed*1.215", "L_slot*2/7"
     .LineTo  "-W_feed*0.780", "L_slot/7"
     .LineTo  "-W_feed/2",     "0"
     ' ---- close polygon at feed end ----
     .LineTo  "W_feed/2",      "0"
     .Create
End With
```

---

## Pattern 4 — Cutout Body Template (for Boolean Subtraction)

When `primitive = "cutout"` or `Role` contains "Cutout":
- Always set `.Material "Vacuum"`.
- Match the exact geometry (same shape as the void you want to carve).
- Do **not** perform the Boolean subtract here; that is done in `boolean_ops.bas`.

```vba
With Extrude
     .Reset
     .Name "FeedSlotCutout"
     .Component "component1"
     .Material "Vacuum"
     .Mode "Pointlist"
     .Height "t_patch"
     .Twist "0.0"
     .Taper "0.0"
     .Origin "0.0", "0.0", "Z_patch"
     .Uvector "1.0", "0.0", "0.0"
     .Vvector "0.0", "1.0", "0.0"
     .Point  "-W_slot/2", "0"
     .LineTo  "W_slot/2", "0"
     .LineTo  "W_slot/2", "L_slot"
     .LineTo "-W_slot/2", "L_slot"
     .LineTo "-W_slot/2", "0"
     .Create
End With
```

---

## Pattern 5 — 2.5D Extrude with Z-offset Transform

When the profile lives at a non-zero Z and `ExtrudeCurve` always starts at Z = 0,
apply a Transform immediately after creation to shift to the correct Z position.

```vba
With ExtrudeCurve
     .Reset
     .Name "PatchOutline"
     .Component "component1"
     .Material "Copper (pure)"
     .Thickness "t_cu"
     .Twistangle "0.0"
     .Taperangle "0.0"
     .DeleteProfile "True"
     .Curve "curve1:polygon1"
     .Create
End With

With Transform
     .Reset
     .Name "component1:PatchOutline"
     .Vector "0", "0", "Z_patch"
     .UsePickedPoints "False"
     .InvertPickedPoints "False"
     .MultipleObjects "False"
     .GroupObjects "False"
     .Repetitions "1"
     .MultipleSelection "False"
     .Transform "Shape", "Translate"
End With
```
