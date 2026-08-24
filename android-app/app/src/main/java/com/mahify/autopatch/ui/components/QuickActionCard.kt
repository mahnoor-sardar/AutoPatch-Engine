package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary

@Composable
fun QuickActionCard(
    label: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .background(SurfaceElevation1, MaterialTheme.shapes.medium)
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.medium)
            .clickable(onClick = onClick)
            .padding(vertical = 16.dp, horizontal = 10.dp),
        horizontalAlignment = androidx.compose.ui.Alignment.CenterHorizontally
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .background(AccentPrimaryMuted, MaterialTheme.shapes.small),
            contentAlignment = androidx.compose.ui.Alignment.Center
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = AccentPrimary,
                modifier = Modifier.size(18.dp)
            )
        }
        Spacer(Modifier.height(8.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = TextPrimary,
            maxLines = 1
        )
    }
}

