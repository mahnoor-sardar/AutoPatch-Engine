package com.mahify.autopatch

enum class DiffLineKind {
    ADD,
    DEL,
    HUNK,
    META,
    CONTEXT
}

data class DiffLine(
    val text: String,
    val kind: DiffLineKind
)

object DiffParser {
    fun parse(diff: String): List<DiffLine> {
        if (diff.isBlank()) {
            return emptyList()
        }
        return diff.split('\n').map { line ->
            val kind = when {
                line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ") ->
                    DiffLineKind.META
                line.startsWith("@@") -> DiffLineKind.HUNK
                line.startsWith("+") -> DiffLineKind.ADD
                line.startsWith("-") -> DiffLineKind.DEL
                else -> DiffLineKind.CONTEXT
            }
            DiffLine(line, kind)
        }
    }
}
