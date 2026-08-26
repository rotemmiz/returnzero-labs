package com.returnzero.benchmark

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.returnzero.benchmark.ui.FeedScreen
import com.returnzero.benchmark.vm.FeedViewModel

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val vm by viewModels<FeedViewModel>()
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface {
                    val nav = rememberNavController()
                    NavHost(navController = nav, startDestination = "feed") {
                        composable("feed") { FeedScreen(vm) }
                    }
                }
            }
        }
    }
}