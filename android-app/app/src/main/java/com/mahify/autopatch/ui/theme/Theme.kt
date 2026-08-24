package com.mahify.autopatch.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat

private val AutoPatchDarkColorScheme = darkColorScheme(
    primary = AccentPrimary,
    onPrimary = TextOnAccent,
    primaryContainer = AccentPrimaryMuted,
    onPrimaryContainer = AccentPrimary,
    secondary = AccentSecondary,
    onSecondary = TextOnAccent,
    background = BackgroundBase,
    onBackground = TextPrimary,
    surface = SurfaceElevation1,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceElevation2,
    onSurfaceVariant = TextSecondary,
    outline = BorderSubtle,
    outlineVariant = BorderStrong,
    error = StatusError,
    onError = TextOnAccent,
    errorContainer = StatusErrorMuted,
    onErrorContainer = StatusError,
    scrim = ScrimOverlay
)

// The app is intentionally dark-first (per spec). A light scheme is provided
// for system-level correctness but the product identity is the dark theme.
private val AutoPatchLightColorScheme = lightColorScheme(
    primary = AccentPrimary,
    background = Color(0xFFF7F7FA),
    surface = Color(0xFFFFFFFF)
)

val AutoPatchShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(18.dp),
    extraLarge = RoundedCornerShape(28.dp)
)

@Composable
fun AutoPatchControlTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    forceDark: Boolean = true, // product is dark-first by design
    content: @Composable () -> Unit
) {
    val useDark = forceDark || darkTheme
    val colorScheme = if (useDark) AutoPatchDarkColorScheme else AutoPatchLightColorScheme

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = colorScheme.background.toArgb()
            window.navigationBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !useDark
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowCompat.getInsetsController(window, view).isAppearanceLightNavigationBars = !useDark
            }
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = AutoPatchTypography,
        shapes = AutoPatchShapes,
        content = content
    )
}

