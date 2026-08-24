package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.StatNumberStyle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextSecondary

@Composable
fun StatCard(
    value: String,
    label: String,
    accentColor: Color,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .background(SurfaceElevation1, MaterialTheme.shapes.medium)
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.medium)
            .padding(vertical = 14.dp, horizontal = 10.dp)
    ) {
        Text(
            text = value,
            style = StatNumberStyle,
            color = accentColor
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextSecondary,
            maxLines = 1
        )
    }
}

