package com.mahify.autopatch.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.TextPrimary

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onActionClick: (() -> Unit)? = null
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium,
            color = TextPrimary
        )
        if (actionLabel != null && onActionClick != null) {
            val interactionSource = remember { MutableInteractionSource() }
            Text(
                text = actionLabel,
                style = MaterialTheme.typography.labelLarge,
                color = AccentPrimary,
                modifier = Modifier.clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    onClick = onActionClick
                )
            )
        }
    }
}

