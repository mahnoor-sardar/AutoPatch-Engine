package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mahify.autopatch.DiffLineKind
import com.mahify.autopatch.DiffParser

@Composable
fun UnifiedDiffViewer(
    diff: String,
    modifier: Modifier = Modifier
) {
    val lines = DiffParser.parse(diff)
    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(Color(0xFF0B1220), RoundedCornerShape(8.dp))
            .padding(10.dp)
            .horizontalScroll(rememberScrollState())
            .verticalScroll(rememberScrollState())
    ) {
        if (lines.isEmpty()) {
            Text(
                text = "// No patch diff",
                color = Color(0xFF94A3B8),
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp
            )
        } else {
            lines.forEach { line ->
                Text(
                    text = if (line.text.isEmpty()) " " else line.text,
                    color = when (line.kind) {
                        DiffLineKind.ADD -> Color(0xFF4ADE80)
                        DiffLineKind.DEL -> Color(0xFFF87171)
                        DiffLineKind.HUNK -> Color(0xFF22D3EE)
                        DiffLineKind.META -> Color(0xFF93C5FD)
                        DiffLineKind.CONTEXT -> Color(0xFFE2E8F0)
                    },
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}
