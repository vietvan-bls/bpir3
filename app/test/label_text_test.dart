import 'package:bpir3_app/screens/ocr.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('nhãn LCSC (ảnh mẫu)', () {
    const text = '3236-B-A09-010\nQTY: 1,500\nC52711259\nMPN:CGA0603X7R104M500JT\n100nF X7R ±20% 50V 0603 Cerami\n'
        'c Capacitors\nCOO:CN\n2\nWM2610290508001\n3246\n1029-0124';
    final r = parseLabelText(text);
    expect(r.lcsc, 'C52711259');
    expect(r.mpn, 'CGA0603X7R104M500JT');
    expect(r.qty, 1500);
    expect(r.order, 'WM2610290508001');
  });

  test('OCR lỗi: tách chữ, I thay 1, dấu chấm', () {
    const text = 'QTY : 1.500\nC5271I259\nMPN: CGA0603 X7R104M 500JT\n';
    final r = parseLabelText(text);
    expect(r.lcsc, 'C52711259');
    expect(r.mpn, 'CGA0603X7R104M500JT');
    expect(r.qty, 1500);
  });

  test('nhãn Digi-Key', () {
    const text = 'DIGI-KEY PART NO: 296-1395-5-ND\nMFR PART #: SN74HC595N\nQTY: 5\n';
    final r = parseLabelText(text);
    expect(r.digikey, '296-1395-5-ND');
    expect(r.mpn, 'SN74HC595N');
    expect(r.qty, 5);
    expect(r.lcsc, '');
    expect(buildCode(mpn: r.mpn, digikey: r.digikey, qty: r.qty), contains('P296-1395-5-ND'));
  });

  test('không nhận nhầm COO:CN, mã đơn thành mã LCSC', () {
    final r = parseLabelText('COO:CN\nCN\nCAP 100\nWM2610290508001');
    expect(r.lcsc, '');
  });

  test('mã giả lập cho server', () {
    expect(buildCode(lcsc: 'c2040', mpn: 'RP2040', qty: 10), '{on:,pc:C2040,pm:RP2040,qty:10}');
  });

  test('chữ OCR thật (Tesseract) từ ảnh nhãn mẫu', () {
    const text = '/,3236-B-A09-010\n652711259\nme MPN: CGA0603X7R1 O4M SOOJT : :\n'
        '40OnF X7R +20% SOV 0603 Cerami Saks Ws ace\nc Capacitors |\nCOO0:CN\nWM2.61029050 8001\n4\n4\n%\nFb ooy\nor';
    final r = parseLabelText(text);
    expect(r.lcsc, 'C52711259');
    expect(r.mpn, 'CGA0603X7R1O4MSOOJT');   // server khớp gần đúng O=0, S=5
    expect(r.order, 'WM2610290508001');
  });
}
