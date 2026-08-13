// Hollow Crown toon shading — ANIME_DIRECTION.md rule 1, "two lighting bands,
// one hard edge".
//
// The whole point is what this shader does NOT do: there is no smooth falloff
// anywhere in it. Incoming light is quantised to a small number of fixed levels
// with a hard step between them, which is the single change that reads as
// "anime" from across the room. Band count and every threshold are uniforms so
// the look can be tuned in the inspector without a shader edit and without a
// rebuild — the director's spec is a rule about the ramp, not about one set of
// numbers.
//
// Rule 3 ("flat colour in the texture, no light baked in") is what makes this
// work. A texture that already contains shading double-shades here and produces
// the mud that makes cel shading look cheap.
//
// NOT YET RUN. Godot could not be installed in the environment this was written
// in; see docs/GODOT_SCENE.md for what that means and what to check first.

shader_type spatial;

// No specular render mode is declared and SPECULAR_LIGHT is never written, so
// this material has no highlight at all. A specular lobe is a smooth gradient by
// construction and would put back exactly what rule 1 removes.
render_mode blend_mix, depth_draw_opaque, cull_back;

group_uniforms colour;

uniform vec4 albedo_colour : source_color = vec4(1.0, 1.0, 1.0, 1.0);
uniform sampler2D albedo_texture : source_color, filter_linear_mipmap, hint_default_white;
// Set by the scene builder: terrain tiles and placeholders are flat colour, an
// imported GLB brings its own map. A bool beats two shaders to keep in step.
uniform bool use_albedo_texture = false;

group_uniforms bands;

// 2 = shadow + lit. 3 = shadow + lit + rim, the spec's default. 4 adds a mid
// band between the terminator and full light, for large surfaces such as the
// ground where two bands can look bald.
uniform int band_count : hint_range(2, 4) = 3;

// Thresholds on N·L, after shadow attenuation. terminator is the hard edge rule
// 1 is named for; the others only exist for the bands above it.
uniform float terminator : hint_range(0.0, 1.0) = 0.42;
uniform float mid_edge : hint_range(0.0, 1.0) = 0.70;
uniform float rim_edge : hint_range(0.0, 1.0) = 0.88;

// Multipliers applied to the light for each band. rim_level above 1.0 is what
// makes the narrow top band read as a rim rather than as more lit surface.
uniform float shadow_level : hint_range(0.0, 2.0) = 0.42;
uniform float mid_level : hint_range(0.0, 2.0) = 0.78;
uniform float lit_level : hint_range(0.0, 2.0) = 1.0;
uniform float rim_level : hint_range(0.0, 2.0) = 1.30;

// Cool shadow against warm light. Rule 5 says neighbouring materials separate by
// hue rather than by value, and cel shading collapses value range by design — so
// the shadow band earns its separation the same way, by shifting hue.
uniform vec3 shadow_tint : source_color = vec3(0.66, 0.72, 0.94);

group_uniforms calibration;

// Godot's own diffuse term carries a 1/PI factor that a custom light() function
// does not. Whether that leaves this material matching a StandardMaterial3D is
// the first thing to check with the editor open; if the scene is uniformly too
// bright or too dark, this is the one knob, not the band levels.
uniform float light_gain : hint_range(0.0, 4.0) = 1.0;

void fragment() {
	vec4 base = albedo_colour;
	if (use_albedo_texture) {
		base *= texture(albedo_texture, UV);
	}

	ALBEDO = base.rgb;
	// ALPHA is deliberately not written: writing it moves the material onto the
	// transparent pass, which reorders it against the outline hull and against
	// every other object on the field.
	METALLIC = 0.0;
	SPECULAR = 0.0;
	ROUGHNESS = 1.0;
}

void light() {
	// ATTENUATION carries the shadow map, so a surface inside a cast shadow lands
	// in the same band as a surface facing away from the light. That is correct
	// for this look: rule 1 allows one shadow tone, not one per cause.
	float ndotl = dot(normalize(NORMAL), normalize(LIGHT));
	float energy = clamp(ndotl, 0.0, 1.0) * ATTENUATION;

	float level = shadow_level;
	if (energy >= terminator) {
		level = lit_level;
		if (band_count >= 4 && energy < mid_edge) {
			level = mid_level;
		}
		if (band_count >= 3 && energy >= rim_edge) {
			level = rim_level;
		}
	}

	vec3 tint = energy >= terminator ? vec3(1.0) : shadow_tint;
	DIFFUSE_LIGHT += ALBEDO * LIGHT_COLOR * tint * level * light_gain;
}
