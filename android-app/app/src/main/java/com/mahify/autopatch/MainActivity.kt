package com.mahify.autopatch

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.mahify.autopatch.ui.navigation.AutoPatchApp
import com.mahify.autopatch.ui.theme.AutoPatchControlTheme

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()

        setContent {
            AutoPatchControlTheme {
                AutoPatchApp()
            }
        }
    }
}