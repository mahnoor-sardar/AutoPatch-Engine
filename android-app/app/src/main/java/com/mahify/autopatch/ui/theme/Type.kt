package com.mahify.autopatch.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Typography hierarchy.
 *
 * Uses the system default (San Francisco/Roboto-equivalent) via FontFamily.Default
 * so no font dependency is required. Swap `FontFamily.Default` for a custom
 * family (e.g. Inter, which reads very "dev tool") once you add it to res/font.
 *
 * Hierarchy mapped to spec:
 *  - App name        -> AppNameStyle (used manually in TopAppBar, not in Typography)
 *  - Page title       -> headlineSmall
 *  - Section titles    -> titleMedium
 *  - Card titles       -> titleSmall
 *  - Status labels     -> labelLarge / labelMedium (semi-bold, tight tracking)
 *  - Supporting desc   -> bodyMedium / bodySmall
 *  - Metadata          -> labelSmall
 */

private val AppFont = FontFamily.Default

val AutoPatchTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.SemiBold,
        fontSize = 24.sp,
        lineHeight = 30.sp,
        letterSpacing = (-0.2).sp
    ),
    titleMedium = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.SemiBold,
        fontSize = 17.sp,
        lineHeight = 22.sp,
        letterSpacing = 0.sp
    ),
    titleSmall = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.Medium,
        fontSize = 15.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.sp
    ),
    bodyMedium = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.1.sp
    ),
    bodySmall = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.Normal,
        fontSize = 13.sp,
        lineHeight = 18.sp,
        letterSpacing = 0.1.sp
    ),
    labelLarge = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.2.sp
    ),
    labelMedium = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.3.sp
    ),
    labelSmall = TextStyle(
        fontFamily = AppFont,
        fontWeight = FontWeight.Medium,
        fontSize = 11.sp,
        lineHeight = 14.sp,
        letterSpacing = 0.3.sp
    )
)

/** Used manually where Typography has no exact slot (e.g. the wordmark in the top bar). */
val AppNameStyle = TextStyle(
    fontFamily = AppFont,
    fontWeight = FontWeight.Bold,
    fontSize = 19.sp,
    letterSpacing = (-0.3).sp
)

/** Large numeric display for stat cards (e.g. "24", "21"). */
val StatNumberStyle = TextStyle(
    fontFamily = AppFont,
    fontWeight = FontWeight.Bold,
    fontSize = 26.sp,
    letterSpacing = (-0.5).sp
)

