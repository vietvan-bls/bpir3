# ML Kit text recognition: chỉ dùng mô hình chữ Latin; các script khác (Trung, Nhật, Hàn, Devanagari)
# được plugin tham chiếu nhưng không đóng gói vào app -> bỏ cảnh báo thiếu lớp khi R8 thu gọn.
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**
