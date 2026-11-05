import 'package:flutter/material.dart';

class FlacifyTheme {
  static const Color spotifyBlack = Color(0xFF121212);
  static const Color cardDark = Color(0xFF181818);
  static const Color elevatedDark = Color(0xFF242424);
  static const Color spotifyEmerald = Color(0xFF1DB954);
  static const Color textPrimary = Color(0xFFFFFFFF);
  static const Color textSecondary = Color(0xFFB3B3B3);
  static const Color dividerColor = Color(0xFF2A2A2A);

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: spotifyBlack,
      primaryColor: spotifyEmerald,
      cardColor: cardDark,
      dividerColor: dividerColor,
      colorScheme: const ColorScheme.dark(
        primary: spotifyEmerald,
        surface: cardDark,
        onSurface: textPrimary,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: spotifyBlack,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: textPrimary,
          fontSize: 22,
          fontWeight: FontWeight.bold,
          letterSpacing: -0.5,
        ),
      ),
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: spotifyBlack,
        selectedItemColor: spotifyEmerald,
        unselectedItemColor: textSecondary,
        type: BottomNavigationBarType.fixed,
        elevation: 10,
      ),
    );
  }
}

