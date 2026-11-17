import 'package:flutter_test/flutter_test.dart';

import 'package:bpir3_app/api.dart';

void main() {
  test('normalize URL', () {
    expect(Api.normalize('192.168.1.1'), 'http://192.168.1.1:8080');
    expect(Api.normalize('abc.trycloudflare.com/'), 'https://abc.trycloudflare.com');
    expect(Api.normalize('http://10.0.0.1:8080/'), 'http://10.0.0.1:8080');
  });
}
