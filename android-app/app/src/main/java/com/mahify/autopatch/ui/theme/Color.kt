package com.mahify.autopatch.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * AutoPatch Control — Color System
 *
 * Design intent: a dark-first, technical, trustworthy palette that reads as a
 * serious developer tool (closer to a terminal/observability product than a
 * "consumer app"). Backgrounds sit in near-black blue-grays rather than pure
 * black so surfaces can differentiate through elevation, not just borders.
 *
 * The accent (Indigo/Violet) is used SPARINGLY — for branding, primary actions,
 * and the AI/automation identity — never for status. Status colors are a
 * separate, disciplined semantic set so the eye never confuses "brand" with
 * "state".
 */

// ---------- Surfaces ----------
val BackgroundBase = Color(0xFF0A0B0F)      // App background — near-black, slight blue
val SurfaceElevation1 = Color(0xFF121319)   // Cards, top bar
val SurfaceElevation2 = Color(0xFF1A1C24)   // Nested cards, bottom sheet, pressed states
val SurfaceElevation3 = Color(0xFF23252F)   // Highest elevation (dialogs, active nav pill)
val BorderSubtle = Color(0xFF272935)        // Hairline dividers / card borders
val BorderStrong = Color(0xFF343743)        // Focus rings, emphasized borders

// ---------- Text ----------
val TextPrimary = Color(0xFFF5F6F8)         // Off-white — headings, key values
val TextSecondary = Color(0xFFA3A7B5)       // Muted gray — descriptions, metadata
val TextTertiary = Color(0xFF6B6F80)        // Timestamps, disabled, placeholder
val TextOnAccent = Color(0xFFFFFFFF)

// ---------- Brand / Accent ----------
val AccentPrimary = Color(0xFF6C63FF)       // Indigo-violet — AutoPatch brand, primary CTA
val AccentPrimaryMuted = Color(0xFF2A2650)  // Accent tinted surface (chips, subtle highlight)
val AccentSecondary = Color(0xFF4C8DFF)     // Supporting blue — links, secondary emphasis

// ---------- Status Semantics ----------
val StatusOnline = Color(0xFF3DD68C)        // Green — healthy / connected / completed
val StatusOnlineMuted = Color(0xFF12291F)   // Background tint for online chips
val StatusWarning = Color(0xFFE8B339)       // Amber — degraded / running / attention
val StatusWarningMuted = Color(0xFF2E2612)
val StatusError = Color(0xFFEF5A5A)         // Red — failed / disconnected / critical
val StatusErrorMuted = Color(0xFF2E1616)
val StatusNeutral = Color(0xFF6B6F80)       // Gray — idle / unknown / disabled system

// ---------- Overlays ----------
val ScrimOverlay = Color(0xCC05060A)
val ShimmerBase = Color(0xFF15161C)
val ShimmerHighlight = Color(0xFF1F212B)

