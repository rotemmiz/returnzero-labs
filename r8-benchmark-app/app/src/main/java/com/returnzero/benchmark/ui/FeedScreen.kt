package com.returnzero.benchmark.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.returnzero.benchmark.data.Article
import com.returnzero.benchmark.vm.FeedViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeedScreen(vm: FeedViewModel) {
    val articles by vm.feed.collectAsState()
    val status by vm.status.collectAsState()
    Scaffold(
        topBar = { TopAppBar(title = { Text("R8 Benchmark") }) }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            Text("status: $status", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(8.dp))
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(8.dp)
            ) {
                items(articles) { a -> ArticleCard(a) }
            }
        }
    }
}

@Composable
private fun ArticleCard(a: Article) {
    Card(modifier = Modifier.fillMaxSize().padding(horizontal = 4.dp)) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            AsyncImage(
                model = a.imageUrl,
                contentDescription = a.title,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize()
            )
            Text(a.title, style = MaterialTheme.typography.titleMedium)
            Text(a.body, style = MaterialTheme.typography.bodyMedium, maxLines = 3)
        }
    }
}