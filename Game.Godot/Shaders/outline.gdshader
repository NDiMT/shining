// Hollow Crown outline — ANIME_DIRECTION.md rule 2, "dark outline on every
// silhouette", inverted hull, width scaled by distance to camera.
//
// Used as the `next_pass` of a toon material, never on its own: the mesh is drawn
// a second time with front faces culled and every vertex pushed out along its
// normal, so what survives the depth test is a shell peeking out from behind the
// silhouette.
//
// THE DISTANCE TERM IS THE POINT. Two naive choices both fail, in opposite
// directions:
//
//   Fixed width in metres  — the outline shrinks with distance in the same
//                            proportion as the unit, so it is scale-correct, but
//                            at the back of a 14-tile grid it falls under a pixel
//                            and shimmers or vanishes.
//   Fixed width in pixels  — the line holds up close but a distant unit is only a
//                            few dozen pixels tall, so a constant 3 px line eats
//                            it. This is exactly the failure the spec names.
//
// So the width is world-space with a sub-linear distance multiplier, then clamped
// in pixels at both ends. distance_falloff picks the blend: 0.0 is pure world
// space, 1.0 is pure screen space, and the default sits between them.
//
// NOT YET RUN — see docs/GODOT_SCENE.md.

shader_type spatial;

// cull_front is what makes this an inverted hull. unshaded because rule 1 owns
// all the lighting and an outline is a flat mass of the line colour by
// definition; shadows_disabled because the hull would otherwise cast a shadow
// slightly larger than the object it belongs to.
render_mode cull_front, unshaded, shadows_disabled;

// Dark line #2A2620 from STYLE_GUIDE.md section 2's shared neutrals. Not black:
// a pure black line against saturated terrain reads as a hole rather than as ink.
uniform vec4 outline_colour : source_color = vec4(0.165, 0.149, 0.125, 1.0);

// Hull thickness in metres at reference_distance. 5 cm against a 1.7 m character
// (rule 4) is roughly the weight of a brush line at the tactical camera's
// working distance.
uniform float width_metres : hint_range(0.0, 0.5) = 0.05;

// The camera's resting distance from the field centre, set by TacticalCamera.cs.
uniform float reference_distance : hint_range(0.5, 200.0) = 26.0;

uniform float distance_falloff : hint_range(0.0, 1.0) = 0.55;

// Hard limits so the line can neither disappear into sub-pixel shimmer nor
// swallow a unit that the camera has zoomed right into.
uniform float min_pixels : hint_range(0.0, 32.0) = 1.5;
uniform float max_pixels : hint_range(0.0, 64.0) = 5.0;

void vertex() {
	vec4 view = MODELVIEW_MATRIX * vec4(VERTEX, 1.0);

	// The normal is transformed by MODELVIEW rather than by NORMAL_MATRIX. That
	// is only equivalent under uniform scale — which is all this project can
	// produce, because PropPlacement.Scale in Game.Rules is a single scalar for
	// precisely this reason. Non-uniform scale would skew the hull.
	vec3 view_normal = normalize((MODELVIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);

	float depth = max(-view.z, 0.001);

	// PROJECTION_MATRIX[1][1] is cot(fov_y / 2) for a perspective camera, so the
	// vertical world extent of one pixel at this depth is 2 * depth / (that *
	// viewport height). An orthographic tactical camera would need the
	// projection's scale instead; the battle camera is perspective.
	float metres_per_pixel = (2.0 * depth)
			/ max(PROJECTION_MATRIX[1][1] * VIEWPORT_SIZE.y, 0.001);

	float width = width_metres * pow(depth / reference_distance, distance_falloff);
	float pixels = clamp(width / metres_per_pixel, min_pixels, max_pixels);

	view.xyz += view_normal * (pixels * metres_per_pixel);
	POSITION = PROJECTION_MATRIX * view;
}

void fragment() {
	ALBEDO = outline_colour.rgb;
}
